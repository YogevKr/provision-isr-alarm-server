import os
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
import logging
import sys
import xml.etree.ElementTree as ET
import re
import json
import aiohttp

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('server.log')
    ]
)

class PagerDutyTrigger:
    def __init__(self, api_token, service_id, from_email, paging_start_time, paging_end_time):
        self.api_token = api_token
        self.service_id = service_id
        self.from_email = from_email
        self.url = "https://api.pagerduty.com/incidents"
        self.paging_start_time = self.parse_time(paging_start_time)
        self.paging_end_time = self.parse_time(paging_end_time)
        self.israel_tz = ZoneInfo("Asia/Jerusalem")

    def parse_time(self, time_str):
        return datetime.strptime(time_str, "%H:%M").time()

    def get_current_israel_time(self):
        return datetime.now(self.israel_tz)

    def is_paging_time(self):
        now = self.get_current_israel_time().time()
        if self.paging_start_time <= self.paging_end_time:
            return self.paging_start_time <= now < self.paging_end_time
        else:  # Handles cases where the range crosses midnight
            return now >= self.paging_start_time or now < self.paging_end_time

    async def trigger_incident(self, title, details, urgency="high"):
        if not self.is_paging_time():
            logging.info(f"Incident not created due to time restrictions: {title}")
            return

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Authorization": f"Token token={self.api_token}",
            "From": self.from_email
        }
        
        payload = {
            "incident": {
                "type": "incident",
                "title": title,
                "service": {
                    "id": self.service_id,
                    "type": "service_reference"
                },
                "urgency": urgency,
                "body": {
                    "type": "incident_body",
                    "details": details
                }
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.url, headers=headers, json=payload) as response:
                if response.status == 201:
                    logging.info(f"PagerDuty incident created successfully: {title}")
                else:
                    logging.error(f"Failed to create PagerDuty incident: {await response.text()}")

class ProvisionISRHandler:
    def __init__(self):
        self.pagerduty_trigger = PagerDutyTrigger(
            os.getenv("PAGERDUTY_API_TOKEN"),
            os.getenv("PAGERDUTY_SERVICE_ID"),
            os.getenv("PAGERDUTY_FROM_EMAIL"),
            os.getenv("PAGING_START_TIME", "00:00"),
            os.getenv("PAGING_END_TIME", "23:59")
        )
        self.pagerduty_alert_types = os.getenv("PAGERDUTY_ALERT_TYPES", "").upper().split(",")
        self.israel_tz = ZoneInfo("Asia/Jerusalem")

    def get_current_israel_time(self):
        return datetime.now(self.israel_tz)

    async def handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        logging.info(f"New connection from {addr}")
        data = await reader.read(4096)
        if data:
            logging.info(f"Received data:\n{data.decode('utf-8', errors='replace')}")
            await self.process_request(data, writer)
        else:
            logging.warning("No data received")
        writer.close()
        await writer.wait_closed()

    async def process_request(self, data, writer):
        try:
            if data.startswith(b'POST'):
                await self.handle_http_post(data, writer)
            else:
                xml_documents = self.split_xml_documents(data.decode('utf-8'))
                for xml_doc in xml_documents:
                    xml_root = ET.fromstring(xml_doc)
                    request_type = self.identify_request_type(xml_root)
                    logging.info(f"Identified request type: {request_type}")
                    
                    if request_type == "heartbeat":
                        await self.handle_heartbeat(xml_root)
                    elif request_type == "alarm":
                        await self.handle_alarm(xml_root)
                    else:
                        logging.warning("Unknown request type")
                
                await self.send_response(writer, b"<response>OK</response>")
        except ET.ParseError as e:
            logging.error(f"XML Parse Error: {str(e)}")
            await self.send_response(writer, b"<error>Invalid XML</error>")
        except Exception as e:
            logging.error(f"Unexpected error in process_request: {str(e)}", exc_info=True)
            await self.send_response(writer, b"<error>Internal Server Error</error>")

    def split_xml_documents(self, data):
        pattern = r'(<\?xml.*?<\/config>)'
        return re.findall(pattern, data, re.DOTALL)

    def identify_request_type(self, xml_root):
        if xml_root.find(".//alarmStatusInfo") is not None:
            return "alarm"
        elif xml_root.find(".//DataTime") is not None and xml_root.find(".//DeviceInfo") is not None:
            return "heartbeat"
        return "unknown"

    async def handle_heartbeat(self, xml_root):
        logging.info("Handling heartbeat request")
        device_info = self.extract_device_info(xml_root)
        logging.info(f"Heartbeat from device: {device_info}")

    async def handle_alarm(self, xml_root):
        logging.info("Handling alarm request")
        alarm_info = xml_root.find(".//alarmStatusInfo")
        device_info = self.extract_device_info(xml_root)
        
        alarm_tasks = []
        for alarm in alarm_info:
            alarm_type = alarm.tag
            alarm_id = alarm.get('id')
            alarm_name = alarm.get('name')
            alarm_status = alarm.text.lower()
            
            logging.info(f"Alarm received: Type={alarm_type}, ID={alarm_id}, Name={alarm_name}, Status={alarm_status}")
            
            if alarm_status == "true":
                alarm_tasks.append(self.process_alarm(alarm_type, alarm_id, alarm_name, device_info))
        
        await asyncio.gather(*alarm_tasks)

    async def handle_http_post(self, data, writer):
        logging.info("Handling HTTP POST request")
        headers, body = self.parse_http_post(data)
        
        if "SendKeepalive" in headers.get("path", ""):
            await self.handle_http_heartbeat(headers)
        elif "SendAlarmData" in headers.get("path", ""):
            await self.handle_http_alarm(body)
        else:
            logging.warning("Unknown HTTP POST request")
            await self.send_response(writer, b"<error>Unknown HTTP POST request</error>")

    def parse_http_post(self, data):
        request = data.decode('utf-8')
        headers, body = request.split('\r\n\r\n', 1)
        headers = dict(line.split(': ', 1) for line in headers.splitlines()[1:] if ': ' in line)
        headers['path'] = request.splitlines()[0].split()[1]
        return headers, body

    async def handle_http_heartbeat(self, headers):
        logging.info("Handling HTTP heartbeat")
        device_info = f"IP: {headers.get('Host', 'Unknown')}"
        logging.info(f"HTTP Heartbeat from device: {device_info}")

    async def handle_http_alarm(self, body):
        logging.info("Handling HTTP alarm")
        try:
            xml_root = ET.fromstring(body)
            smart_type = xml_root.find(".//smartType").text
            device_info = self.extract_http_device_info(xml_root)
            
            logging.info(f"HTTP Alarm received: Type={smart_type}")
            logging.info(f"Device info: {device_info}")
            
            await self.process_http_alarm(smart_type, xml_root, device_info)
        except ET.ParseError as e:
            logging.error(f"XML Parse Error in HTTP alarm: {str(e)}")

    def extract_device_info(self, xml_root):
        device_info = xml_root.find(".//DeviceInfo")
        if device_info is not None:
            return {child.tag: child.text for child in device_info}
        return {}

    def extract_http_device_info(self, xml_root):
        return {
            "mac": xml_root.find(".//mac").text,
            "sn": xml_root.find(".//sn").text,
            "deviceName": xml_root.find(".//deviceName").text
        }

    async def process_alarm(self, alarm_type, alarm_id, alarm_name, device_info):
        current_time = self.get_current_israel_time()
        logging.info(f"Processing alarm at {current_time.isoformat()}: Type={alarm_type}, ID={alarm_id}, Name={alarm_name}")
        logging.info(f"Device Info: {device_info}")
        
        if alarm_type.upper() in self.pagerduty_alert_types:
            title = f"Provision ISR Alarm: {alarm_type} - {alarm_name}"
            details = f"Alarm ID: {alarm_id}\nAlarm Name: {alarm_name}\nDevice Info: {json.dumps(device_info, indent=2)}\nAlarm Time: {current_time.isoformat()}"
            await self.pagerduty_trigger.trigger_incident(title, details)
        else:
            logging.info(f"Alarm type {alarm_type} not in alert list. No PagerDuty incident created.")

    async def process_http_alarm(self, smart_type, xml_root, device_info):
        current_time = self.get_current_israel_time()
        logging.info(f"Processing HTTP alarm at {current_time.isoformat()}: Type={smart_type}")
        logging.info(f"Device Info: {device_info}")

        if smart_type.upper() in self.pagerduty_alert_types:
            alarm_name = xml_root.find(".//name").text if xml_root.find(".//name") is not None else "Unknown"
            title = f"Provision ISR HTTP Alarm: {smart_type} - {alarm_name}"
            details = f"Device Info: {json.dumps(device_info, indent=2)}\nXML Data: {ET.tostring(xml_root, encoding='unicode')}\nAlarm Time: {current_time.isoformat()}"
            await self.pagerduty_trigger.trigger_incident(title, details)
        else:
            logging.info(f"HTTP Alarm type {smart_type} not in alert list. No PagerDuty incident created.")

    def generate_response_xml(self, alarm_type, device_info):
        root = ET.Element("alarmServerResponse")
        root.set("version", "1.0")

        ET.SubElement(root, "status").text = "success"
        ET.SubElement(root, "timestamp").text = self.get_current_israel_time().isoformat(timespec='seconds')
        ET.SubElement(root, "receivedAlarmType").text = alarm_type.upper()

        device_info_elem = ET.SubElement(root, "deviceInfo")
        ET.SubElement(device_info_elem, "deviceName").text = device_info.get("DeviceName", "")
        ET.SubElement(device_info_elem, "deviceNo").text = device_info.get("DeviceNo.", "")
        ET.SubElement(device_info_elem, "sn").text = device_info.get("SN", "")
        ET.SubElement(device_info_elem, "ipAddress").text = device_info.get("ipAddress", "")
        ET.SubElement(device_info_elem, "macAddress").text = device_info.get("macAddress", "")

        server_actions = ET.SubElement(root, "serverActions")
        ET.SubElement(server_actions, "action").text = "alarmLogged"
        ET.SubElement(server_actions, "action").text = "notificationSent"

        ET.SubElement(root, "message").text = "Alarm received and processed successfully"

        return ET.tostring(root, encoding='UTF-8', xml_declaration=True)

    async def send_response(self, writer, content):
        writer.write(content)
        await writer.drain()
        logging.info(f"Sent response:\n{content.decode('utf-8', errors='replace')}")

async def main(host, port):
    handler = ProvisionISRHandler()
    server = await asyncio.start_server(handler.handle_client, host, port)

    addr = server.sockets[0].getsockname()
    logging.info(f'Serving on {addr}')

    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    host = "0.0.0.0"
    port = 6033  # Default port
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    
    israel_tz = ZoneInfo("Asia/Jerusalem")
    israel_time = datetime.now(israel_tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    logging.info(f"Starting Asynchronous Provision-ISR Alarm Server on {host}:{port}")
    logging.info(f"Current Israel time: {israel_time}")
    asyncio.run(main(host, port))
