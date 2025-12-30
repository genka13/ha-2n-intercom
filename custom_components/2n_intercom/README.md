# 2N Intercom (Home Assistant custom integration)

This custom integration adds support for **2N IP intercoms** using the **2N HTTP API** and **RTSP**.

It is based on real devices and the `/api/*` endpoints available on firmware **2.5+**.

## Supported devices / firmware

Tested and intended for:

- **2N IP Style**
- **2N IP Verso 2**
- **2N IP One**

Firmware: **2.5 and newer** (examples in this project were tested on 3.x as well).

## How devices are discovered

To avoid Zeroconf “spam”, discovery is done via **DHCP MAC prefix (OUI)**:

- **`7C:1E:B3`** (shown in Home Assistant as `7C1EB3*`)

In the “Discovered” card, the integration shows **`<host> (<ip>)`** where possible.

You can always add a device manually if discovery is not available in your network.

## Authentication / transport

- Default authentication: **HTTP Digest**
- Optional: **HTTP Basic**
- Default transport: **HTTPS**
- Optional: HTTP
- `verify_ssl` can be disabled for self‑signed certificates (recommended only for trusted LANs).

## Network ports used

- HTTP/HTTPS: 80 / 443 (depending on your device configuration)
- RTSP: **554**
- No broadcast scanning is performed by this integration.

## API endpoints used

### Device info (unique id + device metadata)

- `GET /api/system/info`

Used for:
- Device name (shown in HA)
- Model / SW / HW versions
- **Serial number** (shown as “Serial number” in the HA device page)
- **MAC address** (stored as the device connection)

### Relays (“switches”)

- `GET /api/switch/caps` (read once at setup; creates the switch entities)
- `GET /api/switch/status` (polled; updates `active/locked/held`)
- `GET /api/switch/ctrl?switch=<id>&action=trigger` (used to activate a relay)

### Camera snapshot + preview stream

- `GET /api/camera/snapshot?width=<w>&height=<h>&source=internal`
- For preview streaming (HA “more info” dialog) the integration proxies a multipart stream
  using the same endpoint with `fps>=1` (device feature).

### Events (long-poll, no spam)

- `GET /api/log/caps` (read once at setup; enables only supported event entities)
- `GET /api/log/subscribe?include=new&duration=3600&filter=...`
- `GET /api/log/pull?id=<subscription_id>&timeout=25`

The integration automatically re-subscribes if the device reports an invalid subscription id.

## RTSP video

2N devices expose fixed RTSP endpoints (RTSP server must be enabled on the intercom):

- `rtsp://<host>:554/h264_stream`  *(default, best compatibility)*
- `rtsp://<host>:554/h265_stream`
- `rtsp://<host>:554/mjpeg_stream`

You can change the stream profile in Home Assistant:

**Settings → Devices & Services → 2N Intercom → ⋮ → Options → RTSP stream**

## Entities created

### Camera

- `camera.<device>_camera`
  - Snapshot still image (used for previews)
  - RTSP stream source for live video

### Switches (relays)

For each relay returned by `/api/switch/caps`:

- `switch.<device>_switch_1`
- `switch.<device>_switch_2`
- ...

Notes:
- Relays with `enabled=false` are created but **disabled by default** (enable them in the entity registry).
- Many relays are monostable; `turn_off` simply refreshes state.

### Button

- `button.<device>_door_release`
  - Triggers **Switch 1** (`action=trigger`) by convention.

### Sensors

- `sensor.<device>_activity`
  - Derived from `CallStateChanged` (e.g. idle / ringing / connected).
- `sensor.<device>_last_event` (diagnostic)
  - Stores the last received log event and exposes useful attributes.

### Binary sensors (from log events)

- `binary_sensor.<device>_motion` (MotionDetected)
- `binary_sensor.<device>_door` (DoorStateChanged)
- `binary_sensor.<device>_noise` (NoiseDetected)

Momentary (“pulse”) binary sensors:
- `binary_sensor.<device>_invalid_credential` (**device_class: problem**)  
  Turns on briefly when **CardEnteredInvalid / CodeEnteredInvalid / MobKeyEnteredInvalid** are received (`valid=false`).
- `binary_sensor.<device>_rex` (**device_class: opening**)  
  Turns on briefly on `RexActivated`.
- `binary_sensor.<device>_silent_alarm` (**device_class: problem**)  
  Turns on briefly on `SilentAlarm`.

## Installation (manual)

1. Copy the folder `2n_intercom/` into:

   `config/custom_components/2n_intercom/`

2. Restart Home Assistant.
3. Add the integration via UI:

   **Settings → Devices & Services → Add integration → “2N Intercom”**

## Troubleshooting

- **No preview image / blank dialog**: ensure the snapshot endpoint works and that the user has permissions.
- **RTSP stream does not play**: enable RTSP server on the 2N device and verify port 554 is reachable.
- **No events**: check `/api/log/caps` for supported events and make sure the user has the required privileges.
- **Self-signed SSL**: set `verify_ssl = false` during setup.

---

**Disclaimer**: This is a community / custom integration and is not affiliated with 2N / Axis Communications.
