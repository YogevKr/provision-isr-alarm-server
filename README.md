# Provision ISR Alarm Server

## Overview

This project implements an asynchronous server for handling alarms from Provision ISR devices. It processes both XML and HTTP POST requests, logs all alarms, and can trigger PagerDuty incidents for specified alarm types. The server operates in Israel's time zone and correctly handles Daylight Saving Time (DST) transitions.

## Features

- Asynchronous handling of multiple client connections
- Support for both XML and HTTP POST alarm formats
- Configurable PagerDuty integration for alert notifications
- Comprehensive logging of all received alarms
- Time-based restrictions for creating PagerDuty incidents
- Automatic handling of Israel's time zone and DST

## Requirements

- Python 3.11+
- Docker and Docker Compose (for containerized deployment)

## Configuration

The server is configured using environment variables:

- `PAGERDUTY_API_TOKEN`: Your PagerDuty API token
- `PAGERDUTY_SERVICE_ID`: The ID of the PagerDuty service to create incidents for
- `PAGERDUTY_FROM_EMAIL`: The email address to use as the sender for PagerDuty incidents
- `PAGERDUTY_ALERT_TYPES`: A comma-separated list of alarm types that should trigger PagerDuty alerts
- `PAGING_START_TIME`: The start time for allowing PagerDuty incidents (format: "HH:MM", default: "00:00")
- `PAGING_END_TIME`: The end time for allowing PagerDuty incidents (format: "HH:MM", default: "23:59")

## Setup and Deployment

1. Clone the repository:
   ```
   git clone https://github.com/yogevkr/provision-isr-alarm-server.git
   cd provision-isr-alarm-server
   ```

2. Create a `.env` file in the project root with your configuration:
   ```
   PAGERDUTY_API_TOKEN=your_api_token
   PAGERDUTY_SERVICE_ID=your_service_id
   PAGERDUTY_FROM_EMAIL=your_email@example.com
   PAGERDUTY_ALERT_TYPES=MOTION,FIRE,TRIPWIREALARM
   PAGING_START_TIME=09:00
   PAGING_END_TIME=17:00
   ```

3. Build and start the Docker container:
   ```
   docker-compose up --build
   ```

The server will start and listen on port 6033 by default.

## Usage

The server accepts the following XML format request:

   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <config>
     <alarmStatusInfo>
       <tripwireAlarm type="boolean" id="4" name="Entrance">true</tripwireAlarm>
     </alarmStatusInfo>
     <DeviceInfo>
       <DeviceName>Device Name</DeviceName>
       <DeviceNo.>1</DeviceNo.>
       <SN>DEVICE_SERIAL_NUMBER</SN>
       <ipAddress>192.168.1.100</ipAddress>
       <macAddress>00:11:22:33:44:55</macAddress>
     </DeviceInfo>
   </config>
   ```

## Contributing

Contributions to improve the Provision ISR Alarm Server are welcome. Please feel free to submit issues and pull requests.
