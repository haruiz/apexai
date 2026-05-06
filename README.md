ApexAI 
=======

ApexAI is a real-time AI coaching application for track-day drivers. It includes
a FastAPI telemetry server that ingests Racelogic VBOX `.vbo` files or live CAN
frames and streams normalized telemetry, an Android mobile coaching app for
receiving live driving data and running on-device inference, and a Next.js web
UI for visualizing sessions from the data. The system is built as an end-to-end racing coach:
telemetry flows from the server to the UI and mobile client, the mobile app
turns that stream into driver feedback, and the core loop is designed to run
without depending on a cloud service.

## Application Components

- Telemetry server: supports Racelogic VBOX `.vbo` replay and live CAN input,
  normalizes telemetry into one packet shape, exposes control APIs, and streams
  live packets over WebSocket and Server-Sent Events.
- Web UI: a Next.js telemetry dashboard for visualizing a top-down GPS race map,
  car position, orientation, replay state, replay speed, and sensor channels.
- Mobile app: an Android coaching client intended to receive streamed telemetry
  and run on-device inference for driver coaching feedback.
- Packaging and tooling: `uv` console scripts and `make` shortcuts run the
  server, launch the UI, and package the static UI into the Python package.

## Roadmap

- [x] Develop the telemetry streaming simulator server for replaying VBOX data
  over HTTP, WebSocket, and SSE.
- [x] Add a live CAN source that can read a CAN adapter through `python-can`,
  decode frames with a DBC file, and stream normalized packets through the same
  WebSocket and SSE endpoints.
- [x] Build a simulator frontend that visualizes telemetry in real time according
  to the configured streaming frequency.
- [x] Build a mobile application that receives streamed telemetry data and runs
  on-device inference to generate coaching instructions. Sebastian already has
  related work started here.
- [ ] Develop an RL pipeline to fine-tune a Gemma model for racing coaching
  commands.
- [x] Integrate a memory bank where telemetry data can be queued and used for
  lookahead prediction, so the coaching pipeline can anticipate upcoming driver
  needs. Vikram already has related work started here.

[//]: # (## Pipeline Diagram)

[//]: # ()
[//]: # (![Telemetry pipeline]&#40;images/telemetry-pipeline.png&#41;)

## Install

This project assumes `uv` is used for Python dependency management and run
scripts. From the repository root, install or sync the package environment with:

```bash
uv sync
```

`uv run` will also create the environment and install dependencies on demand.

The packaged UI is served by Python through `uv run apexai-ui`. Rebuilding the
static UI from source requires Node.js and npm because the source app is built
with Next.js.

## Quick Start

Start the telemetry server:

```bash
uv run apexai-server --vbo-file ./data/sample.vbo --autostart --replay-speed 1.0
```

Build the static UI once, then serve it in another terminal:

```bash
make ui-build
uv run apexai-ui
```

The UI defaults to `http://localhost:3000` and connects to the API at
`http://localhost:8000`.

## GitHub Pages Walkthrough

The `docs/` folder contains a static walkthrough app for GitHub Pages. In the
repository settings, set Pages to deploy with **GitHub Actions**. The
`.github/workflows/pages.yml` workflow uploads only `docs/`, so private or
unavailable submodules are not cloned during the Pages deployment.

For local preview:

```bash
cd docs
python3 -m http.server 4173
```

Then open `http://localhost:4173`.

## Telemetry Server

For repeated local runs, configure `.env` and start through `make`.

`.env`:

```env
SOURCE=vbo
VBO_FILE=/absolute/path/to/session.vbo
DBC_FILE=
CAN_INTERFACE=socketcan
CAN_CHANNEL=can0
CAN_BITRATE=
HOST=0.0.0.0
PORT=8000
REPLAY_SPEED=1.0
STREAM_INTERVAL=
LOOP=
AUTOSTART=--autostart
```

Start the server:

```bash
make start
```

`STREAM_INTERVAL=` means replay uses the original VBO timestamp intervals. Set
`STREAM_INTERVAL=5` to stream one packet every 5 seconds. `LOOP=` means the
replay stops at the end. Set `LOOP=--loop` to restart from the first sample
after the final sample.

Changing `STREAM_INTERVAL` is useful for evaluating the downstream phone
pipeline at different streaming frequencies before running against the cadence
expected during real field sessions.

You can override `.env` values from the command line:

```bash
make start SOURCE=vbo VBO_FILE=./data/session.vbo PORT=8000 STREAM_INTERVAL=5 LOOP=--loop
```

The direct `uv` command is:

```bash
uv run apexai-server --vbo-file ./data/sample.vbo --autostart --replay-speed 1.0
```

Equivalent Python module command through `uv`:

```bash
uv run python -m apexai.server --vbo-file ./data/sample.vbo --autostart --replay-speed 1.0
```

All server options:

```bash
uv run apexai-server \
  --source vbo \
  --vbo-file ./data/session.vbo \
  --host 0.0.0.0 \
  --port 8000 \
  --replay-speed 1.0 \
  --stream-interval 5 \
  --loop \
  --autostart
```

On startup the server prints the VBO path, sample count, available columns,
approximate duration, replay speed, stream interval, loop setting, and autostart
setting. Omit `--stream-interval` to replay using the original VBO timestamp
intervals. Set it to a number of seconds to stream at a fixed cadence, for
example `5` for every 5 seconds or `60` for every minute.

## CAN Source

The server can also stream live CAN data through the same telemetry output
endpoints. CAN frames are read with `python-can`, decoded with `cantools` and a
DBC file, normalized into `TelemetryPacket`, then published to:

- WebSocket: `ws://localhost:8000/ws/telemetry`
- SSE: `http://localhost:8000/events/telemetry`

SocketCAN or virtual CAN example:

```bash
uv run apexai-server \
  --source can \
  --dbc-file ./data/vehicle.dbc \
  --can-interface socketcan \
  --can-channel vcan0 \
  --autostart
```

USB-C CAN adapters are handled as CAN interfaces. For example, many serial CAN
adapters use `slcan` and a device path:

```bash
uv run apexai-server \
  --source can \
  --dbc-file ./data/vehicle.dbc \
  --can-interface slcan \
  --can-channel /dev/ttyUSB0 \
  --can-bitrate 500000 \
  --autostart
```

The exact `--can-interface` and `--can-channel` values depend on the adapter and
operating system. Common `python-can` interfaces include `socketcan`, `slcan`,
`pcan`, `vector`, and `virtual`.

CAN source controls:

- `/replay/start`, `/replay/pause`, `/replay/stop`, and `/replay/reset` control
  live ingestion.
- `/replay/stream-interval` can throttle publishing, or use `{"seconds": null}`
  to publish every decoded frame.
- `/replay/speed` and `/replay/seek` are VBO-only concepts and return an error
  for live CAN.

The normalized CAN fields are resolved from common DBC signal names such as
`VehicleSpeed`, `Throttle`, `BrakePressure`, `SteeringAngle`, `CurrentGear`,
`Latitude`, and `Longitude`. All decoded signals are also preserved in `raw`, so
the Android app can read vehicle-specific values before the normalization map is
tuned for your sensor box.

## Telemetry Source Implementation Guide

The server now has two source classes in
`src/apexai/server/telemetry_sources.py`:

- `VBOTelemetrySource`: replays parsed VBO rows. It supports start, pause, stop,
  reset, seek, replay speed, fixed frequency, source timestamp timing, and loop.
- `CANTelemetrySource`: reads live CAN frames, decodes them with a DBC, maps
  common signal names into the normalized packet fields, and publishes every
  decoded frame or a throttled output frequency.

Both classes publish packets to the same `Broadcaster`, so clients use the same
stream URLs regardless of the input protocol:

- `GET /events/telemetry` for SSE
- `GET /ws/telemetry` for WebSocket
- `GET /telemetry/latest` for the most recent packet
- `GET /telemetry/trace` for preloaded GPS trace points when the source has
  recorded GPS samples

### CLI arguments and hints

| Argument | Applies to | Description | Hint |
|---|---|---|---|
| `--source vbo` | VBO | Selects recorded VBO replay. | Use this for local simulation and testing with `.vbo` files. |
| `--source can` | CAN | Selects live CAN ingestion. | Use this with a vehicle sensor box, USB-C CAN adapter, SocketCAN, or virtual CAN. |
| `--vbo-file` | VBO | Path to a Racelogic VBOX `.vbo` file. | Required for `--source vbo`. |
| `--dbc-file` | CAN | Path to the DBC file used to decode CAN frame IDs and payload bytes. | Required for `--source can`; without a DBC the server cannot know what raw bytes mean. |
| `--can-interface` | CAN | `python-can` backend name. | Common values: `socketcan`, `slcan`, `virtual`, `pcan`, `vector`. |
| `--can-channel` | CAN | Channel or device passed to `python-can`. | Examples: `can0`, `vcan0`, `test`, `/dev/ttyUSB0`. |
| `--can-bitrate` | CAN | Optional CAN bus bitrate in bits per second. | Use values like `500000`; often needed for USB serial CAN adapters. |
| `--host` | Both | Host address for the FastAPI server. | `0.0.0.0` allows other devices on the network to connect. |
| `--port` | Both | TCP port for HTTP, SSE, and WebSocket. | Default is `8000`. |
| `--replay-speed` | VBO | Multiplier for VBO timestamp playback. | `2.0` plays twice as fast. Not used for live CAN. |
| `--stream-interval` | Both | Fixed seconds between published packets. | `0.1` is about 10 Hz. Omit for source-driven timing. |
| `--loop` | VBO | Restarts replay after the final VBO sample. | Useful for long-running UI or Android tests. |
| `--autostart` | Both | Starts the selected source when the server starts. | Without it, call `POST /replay/start`. |

### Control API behavior

| Endpoint | VBO behavior | CAN behavior |
|---|---|---|
| `POST /replay/start` | Starts or resumes file replay. | Starts or resumes live CAN reads. |
| `POST /replay/pause` | Pauses at the current sample index. | Pauses live publication. |
| `POST /replay/stop` | Stops and resets to the first sample. | Stops ingest and releases the CAN bus. |
| `POST /replay/reset` | Clears latest packet and resets index. | Clears latest packet and published packet count. |
| `POST /replay/seek` | Moves to a VBO sample index. | Returns an error because live CAN has no seekable index. |
| `POST /replay/speed` | Changes VBO replay speed. | Returns an error because live CAN timing is vehicle-driven. |
| `POST /replay/stream-interval` | Sets fixed VBO output cadence or restores VBO timestamps. | Throttles CAN output or publishes every decoded frame. |

### Frequency examples

Set either VBO or CAN output to about 10 Hz:

```bash
curl -X POST http://localhost:8000/replay/stream-interval \
  -H "Content-Type: application/json" \
  -d '{"seconds": 0.1}'
```

Restore source-driven timing:

```bash
curl -X POST http://localhost:8000/replay/stream-interval \
  -H "Content-Type: application/json" \
  -d '{"seconds": null}'
```

For VBO, source-driven timing means the original VBO timestamps adjusted by
`--replay-speed`. For CAN, source-driven timing means every decoded CAN frame is
published as it arrives from the adapter.

## Telemetry UI

The repository contains a root-level Next.js app in `ui/`. It connects to the
FastAPI server, preloads the full GPS trace from `/telemetry/trace`, shows a
stable top-down race map, draws the streamed driven path, computes vehicle
position in meters from the first GPS sample, computes orientation from the
telemetry heading or GPS bearing, and displays controls for replay state, replay
speed, and streaming frequency.

Build the static UI into the Python package:

```bash
make ui-build
```

Serve the packaged static UI without npm or Next.js:

```bash
uv run apexai-ui
```

Optional static server arguments:

```bash
uv run apexai-ui --host 0.0.0.0 --port 3000
```

`make ui` wraps `uv run apexai-ui`. `make ui-dev` is kept as an alias for
`make ui`.

## Packaged UI

`make ui-build` writes the static site into `src/apexai/ui/static`. When those
assets are present, `apexai-server` serves the UI from `/` while keeping the API
routes such as `/state`, `/replay/start`, and `/ws/telemetry` available.

## Test The Server

In one terminal, start the server:

```bash
make start
```

In another terminal, verify health and state:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/state
```

If `AUTOSTART` is empty in `.env`, start replay manually:

```bash
curl -X POST http://localhost:8000/replay/start
```

To test SSE streaming from another terminal:

```bash
curl -N http://localhost:8000/events/telemetry
```

You should see events like:

```text
event: telemetry
data: {"sequence":0,"timestamp":...}
```

## Streaming Server Control HTTP API

Health and state:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/state
curl http://localhost:8000/telemetry/latest
curl http://localhost:8000/telemetry/trace
```

Replay control:

```bash
curl -X POST http://localhost:8000/replay/start
curl -X POST http://localhost:8000/replay/pause
curl -X POST http://localhost:8000/replay/stop
curl -X POST http://localhost:8000/replay/reset
```

Change replay speed:

```bash
curl -X POST http://localhost:8000/replay/speed \
  -H "Content-Type: application/json" \
  -d '{"speed": 2.0}'
```

Change streaming interval:

```bash
curl -X POST http://localhost:8000/replay/stream-interval \
  -H "Content-Type: application/json" \
  -d '{"seconds": 5}'
```

Restore source timestamp intervals:

```bash
curl -X POST http://localhost:8000/replay/stream-interval \
  -H "Content-Type: application/json" \
  -d '{"seconds": null}'
```

Seek to a sample index:

```bash
curl -X POST http://localhost:8000/replay/seek \
  -H "Content-Type: application/json" \
  -d '{"index": 100}'
```

## Consume telemetry

## WebSocket client

Connect to `ws://localhost:8000/ws/telemetry` while replay is playing.

```html
<script>
  const socket = new WebSocket("ws://localhost:8000/ws/telemetry");

  socket.onmessage = (event) => {
    const packet = JSON.parse(event.data);
    console.log("telemetry", packet);
  };

  socket.onopen = () => console.log("connected");
  socket.onclose = () => console.log("disconnected");
</script>
```

## Server-Sent Events client

Connect to `http://localhost:8000/events/telemetry` while replay is playing.

```html
<script>
  const events = new EventSource("http://localhost:8000/events/telemetry");

  events.addEventListener("telemetry", (event) => {
    const packet = JSON.parse(event.data);
    console.log("telemetry", packet);
  });
</script>
```

## Telemetry packets

Each streamed packet is normalized to this shape:

```json
{
  "sequence": 0,
  "timestamp": 0.0,
  "latitude": null,
  "longitude": null,
  "speed": null,
  "heading": null,
  "altitude": null,
  "satellites": null,
  "throttle": null,
  "brake": null,
  "steering": null,
  "gear": null,
  "lap": null,
  "raw": {}
}
```

Missing optional VBO fields are returned as `null`. The original parsed row is
preserved in `raw`.
