# MTDx62 Presence Sensor

Home Assistant integration for the **MTD062-MB** (5.8 GHz) and **MTD262-MB** (24 GHz) human
presence sensors, reached over Modbus RTU or Modbus TCP.

The sensor detects a person by breathing and small movements, not just by motion, so it keeps
reporting presence for someone sitting still. This integration turns that into an occupancy
binary sensor, adds illuminance and target distance, and exposes the device's own health.

![Overview of the sensor with the infrared remote](docs/images/device-overview.webp)

The sensor is a ceiling-mounted radar unit with an RS485 interface, configured over the bus or
with an infrared remote. It reaches Home Assistant through Home Assistant's own
[Modbus](https://www.home-assistant.io/integrations/modbus/) integration: this integration never
opens the port itself, so several sensors on one bus, and other Modbus devices, share the
connection.

![Side view of the sensor](docs/images/device-side.webp)

Dimensions, the internals of both radio versions and everything about the protocol — register
map, health codes, what the device does when the bus is cut — live in the
[library repository](https://github.com/sergeyastakhov/mtdx62-modbus-library#the-device).

## Supported devices

| Model | Radio | Connection |
|---|---|---|
| MTD062-MB | 5.8 GHz | RS485 (Modbus RTU) or a Modbus TCP gateway |
| MTD262-MB | 24 GHz | RS485 (Modbus RTU) or a Modbus TCP gateway |

Both models report the same registers, so the model is selected when the device is added.

The same housing is also made without Modbus: the **MTD061-RC** (5.8 GHz) and **MTD261-RC**
(24 GHz) switch a dry contact — a relay up to 24 V and 100 mA — and know nothing about Modbus.
Those are not supported here; their signal goes to a binary input or a smart relay.

Devices that look the same are sold under other names, and Bluetooth variants exist. Only a model
whose name ends in `-MB` speaks Modbus RTU; check the label on the back before buying.

## Installation

The integration is distributed through the [Marketplace](https://www.home-assistant.io/integrations/marketplace):
add this repository, install **MTDx62 Presence Sensor**, restart Home Assistant.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=mtdx62)

## Setup

One device is one config entry. Several sensors on one RS485 bus share a single Modbus
connection automatically: add each one separately with its own bus address, and the connection
is reused.

1. **Settings → Devices & services → Add integration → MTDx62 Presence Sensor**.
2. Choose **Modbus TCP** for a gateway, or **Serial port (Modbus RTU)** for a USB-RS485 adapter.
3. Enter the connection settings and the sensor's address on the bus (1–247).
4. Pick the model that is on the ceiling.

Default values match the factory settings: 9600 baud, odd parity, one stop bit, unit id 1, TCP
port 502.

## Entities

| Entity | Meaning | Notes |
|---|---|---|
| Presence | someone is in the room | occupancy class, updated every 5 seconds |
| Illuminance | ambient light as the sensor sees it | lux |
| Target distance | distance to the detected target | centimetres, disabled by default |
| Device status | the sensor's own health code | diagnostic, disabled by default |
| Application version | firmware of the sensor | diagnostic, disabled by default |
| Radar version | firmware of the radar module | diagnostic, disabled by default |

Presence, illuminance and distance are shown only while the sensor reports that it is running
(health code 1, self-test passed). During power-up and after a self-test failure they go
unavailable instead of showing numbers nobody should trust; the device status entity and
diagnostics keep working, so the reason is visible. The state is what the sensor reports: there is
no extra filtering or debounce in Home Assistant. The entry delay, departure delay and sensitivity
of the sensor itself decide how quickly presence clears.

## How data is updated

The integration asks the sensor for four registers every 5 seconds, in one request per device.
The Modbus connection is shared with other integrations through Home Assistant's own `modbus`
integration, so nothing competes for the port.

If the sensor stops answering, entities go unavailable after three failed polls in a row; a
single lost frame on a busy bus does not disturb anything. The connection recovers by itself
when the sensor answers again — no restart, no reloading of the entry.

From the entry's page you can download diagnostics: measurements, the sensor's parameters, raw
register values and firmware versions, with the serial port path redacted.

## Known limitations

- The sensor's configuration (detection range, delays, sensitivity, light threshold) is **read
  only**. Changing it from Home Assistant is not implemented yet; use the infrared remote the
  sensor ships with.
- Electronics in metal enclosures, elevators and metal-panel rooms break the radar's readings;
  that is a property of the sensor, not of this integration.
- A reading that the vendor documented ambiguously (two parameter registers) is reported in
  diagnostics but not used.
- Polling is fixed at 5 seconds. On a slow bus with many sensors this is a noticeable load.

## Troubleshooting

- **"Could not reach the sensor"** — check the address on the bus, the baud rate and parity, and
  that no other program holds the serial port.
- **"This sensor is already used with different connection settings"** — the same device is
  already configured with other link settings. Change them in the existing entry instead of
  adding a second one.
- **Presence stays on after everyone left** — that is the sensor's departure delay, set on the
  device. Check the device status entity for a health code.

## Removal

Delete the config entry under **Settings → Devices & services**. The Modbus connection is
released when the last entry using it is removed. Nothing is written to the sensor, so removing
the integration leaves the device exactly as it was.

## Development

The protocol lives in a separate package, [`mtdx62-modbus-library`](https://pypi.org/project/mtdx62-modbus-library/),
imported as `mtdx62_modbus_library`, built on
Home Assistant's `modbus-connection`. The integration only wires that package to entities and the
config flow; requirements and design live in `openspec/`.

## Author

Sergey Astakhov — [sergeyastakhov@mail.ru](mailto:sergeyastakhov@mail.ru),
[github.com/sergeyastakhov](https://github.com/sergeyastakhov).

Source and issues: <https://github.com/sergeyastakhov/ha-mtdx62>. MIT licensed.
