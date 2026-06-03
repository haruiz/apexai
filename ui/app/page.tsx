"use client";

import SportsScoreIcon from "@mui/icons-material/SportsScore";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import PauseIcon from "@mui/icons-material/Pause";
import StopIcon from "@mui/icons-material/Stop";
import ReplayIcon from "@mui/icons-material/Replay";
import LoopIcon from "@mui/icons-material/Loop";
import {
  Box,
  Card,
  CardContent,
  Chip,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
  Divider,
  Button
} from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { ChangeEvent, useEffect, useMemo, useRef, useState, memo } from "react";
import { ReplayState, TelemetryPacket, useTelemetryStore } from "./store";

type SensorKey = "speed" | "throttle" | "brake" | "steering" | "heading" | "altitude" | "satellites" | "gear";
type ColorMapKey = "apex" | "turbo" | "viridis" | "magma" | "icefire";

type TrackPoint = {
  sequence: number;
  timestamp: number;
  latitude: number;
  longitude: number;
  heading: number | null;
  xMeters: number;
  yMeters: number;
  speed?: number | null;
  throttle?: number | null;
  brake?: number | null;
  steering?: number | null;
  altitude?: number | null;
  satellites?: number | null;
  gear?: number | null;
};

type TraceSample = {
  sequence: number;
  timestamp: number;
  latitude: number;
  longitude: number;
  heading: number | null;
  speed?: number | null;
  throttle?: number | null;
  brake?: number | null;
  steering?: number | null;
  altitude?: number | null;
  satellites?: number | null;
  gear?: number | null;
};

const DEFAULT_STATE: ReplayState = {
  status: "idle",
  current_index: 0,
  total_samples: 0,
  replay_speed: 1,
  stream_interval: null,
  loop: false,
  vbo_file: "",
  source: "vbo",
  source_file: null
};
const DEFAULT_API_URL = "http://localhost:8000";
const SENSOR_OPTIONS: Array<{ key: SensorKey; label: string; unit: string }> = [
  { key: "speed", label: "Speed", unit: "source" },
  { key: "throttle", label: "Throttle", unit: "%" },
  { key: "brake", label: "Brake", unit: "%" },
  { key: "steering", label: "Steering", unit: "deg" },
  { key: "heading", label: "Heading", unit: "deg" },
  { key: "altitude", label: "Altitude", unit: "m" },
  { key: "satellites", label: "Satellites", unit: "" },
  { key: "gear", label: "Gear", unit: "" }
];
const COLORMAP_OPTIONS: Array<{ key: ColorMapKey; label: string }> = [
  { key: "apex", label: "Apex telemetry" },
  { key: "turbo", label: "Turbo" },
  { key: "viridis", label: "Viridis" },
  { key: "magma", label: "Magma" },
  { key: "icefire", label: "Icefire" }
];
export default function Home() {
  const reconnectRef = useRef<number | null>(null);
  const [sensorField, setSensorField] = useState<SensorKey>("speed");
  const [colorMap, setColorMap] = useState<ColorMapKey>("apex");
  const {
    apiUrl,
    connection,
    latest,
    history,
    setApiUrl,
    setConnection,
    setTelemetryActive,
    resetTelemetry,
    pushPacket,
    pushPackets
  } = useTelemetryStore();

  const endpoint = useMemo(() => normalizeEndpoint(apiUrl), [apiUrl]);

  const stateQuery = useQuery({
    queryKey: ["replay-state", endpoint],
    queryFn: () => fetchJson<ReplayState>(`${endpoint}/state`),
    enabled: Boolean(endpoint),
    refetchInterval: 1000
  });

  const state = stateQuery.data ?? DEFAULT_STATE;
  const sourceFile = state.source_file ?? state.vbo_file;

  const latestQuery = useQuery({
    queryKey: ["latest-telemetry", endpoint],
    queryFn: () => fetchJson<TelemetryPacket | null>(`${endpoint}/telemetry/latest`),
    enabled: Boolean(endpoint),
    refetchInterval: connection === "live" ? false : 1000
  });

  const traceQuery = useQuery({
    queryKey: ["telemetry-trace", endpoint, sourceFile],
    queryFn: () => fetchJson<TraceSample[]>(`${endpoint}/telemetry/trace`),
    enabled: Boolean(endpoint),
    staleTime: Infinity
  });

  const lastIndexRef = useRef<number>(0);
  useEffect(() => {
    if (state.current_index === 0 && lastIndexRef.current > 0) {
      resetTelemetry();
    }
    lastIndexRef.current = state.current_index;
  }, [state.current_index, resetTelemetry]);

  const handlePlayPause = async () => {
    if (!endpoint) return;
    try {
      if (state.status === "playing") {
        await postJson(`${endpoint}/replay/pause`);
      } else {
        await postJson(`${endpoint}/replay/start`);
      }
      stateQuery.refetch();
    } catch (err) {
      console.error(err);
    }
  };

  const handleStop = async () => {
    if (!endpoint) return;
    try {
      await postJson(`${endpoint}/replay/stop`);
      resetTelemetry();
      stateQuery.refetch();
    } catch (err) {
      console.error(err);
    }
  };

  const handleReset = async () => {
    if (!endpoint) return;
    try {
      await postJson(`${endpoint}/replay/reset`);
      resetTelemetry();
      stateQuery.refetch();
    } catch (err) {
      console.error(err);
    }
  };

  const handleToggleLoop = async () => {
    if (!endpoint) return;
    try {
      await postJson(`${endpoint}/replay/loop`, { loop: !state.loop });
      stateQuery.refetch();
    } catch (err) {
      console.error(err);
    }
  };

  const handleChangeSpeed = async (speed: number) => {
    if (!endpoint) return;
    try {
      await postJson(`${endpoint}/replay/speed`, { speed });
      stateQuery.refetch();
    } catch (err) {
      console.error(err);
    }
  };

  const handleChangeInterval = async (seconds: number | null) => {
    if (!endpoint) return;
    try {
      await postJson(`${endpoint}/replay/stream-interval`, { seconds });
      stateQuery.refetch();
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    const origin = window.location.origin;
    const isNextDev = window.location.port === "3000";
    const base = process.env.NEXT_PUBLIC_APEXAI_API_URL ?? (isNextDev ? DEFAULT_API_URL : origin);
    setApiUrl(`${base}/events/telemetry`);
  }, [setApiUrl]);

  useEffect(() => {
    setTelemetryActive(Boolean(endpoint));
    resetTelemetry();
  }, [endpoint, resetTelemetry, setTelemetryActive]);

  useEffect(() => {
    if (latestQuery.data) {
      pushPacket(latestQuery.data);
    }
  }, [latestQuery.data, pushPacket]);

  useEffect(() => {
    if (!endpoint) {
      return;
    }

    let closed = false;
    let buffer: TelemetryPacket[] = [];
    const flushInterval = setInterval(() => {
      if (buffer.length > 0) {
        pushPackets(buffer);
        buffer = [];
      }
    }, 50); // Flush every 50ms (20Hz)

    function connect() {
      if (closed) {
        return;
      }
      setConnection("connecting");
      const source = new EventSource(`${endpoint}/events/telemetry`);

      source.onopen = () => setConnection("live");
      source.addEventListener("telemetry", (event) => {
        if (!useTelemetryStore.getState().telemetryActive) {
          return;
        }
        const packet = JSON.parse(event.data) as TelemetryPacket;
        buffer.push(packet);
      });
      source.onerror = () => {
        if (closed) {
          source.close();
          return;
        }
        setConnection("offline");
        source.close();
        reconnectRef.current = window.setTimeout(connect, 1500);
      };
    }

    connect();

    return () => {
      closed = true;
      clearInterval(flushInterval);
      if (reconnectRef.current) {
        window.clearTimeout(reconnectRef.current);
      }
    };
  }, [endpoint, pushPackets, setConnection]);

  const trace = traceQuery.data ?? [];
  const track = useMemo(() => buildTrack(trace, null, 1200), [trace]);
  const traceOrigin = track[0] ?? null;
  const drivenTrack = useMemo(() => buildTrack(history, traceOrigin), [history, traceOrigin]);
  const projectionOrigin = traceOrigin ?? drivenTrack[0] ?? null;
  const currentPoint = useMemo(() => projectPacketFromOrigin(latest, projectionOrigin), [latest, projectionOrigin]);
  const orientation = useMemo(() => computeOrientation(latest), [latest]);
  const bounds = useMemo(() => trackBounds(track.length > 0 ? track : drivenTrack), [track, drivenTrack]);
  const sensorRange = useMemo(() => dataRange(track, sensorField), [sensorField, track]);
  const sourceLabel = state.source === "can" ? "CAN raw stream" : "VBOX telemetry";
  const sourceStatus = `${state.status} - ${state.current_index}/${state.total_samples}`;
  const selectedSensor = selectedSensorLabel(sensorField);
  const sensorCards: Array<{ label: string; value: string; unit?: string }> =
    latest?.source === "can"
      ? [
          { label: "Source", value: "CAN raw" },
          { label: "Sequence", value: formatNumber(latest.sequence, 0) },
          { label: "Timestamp", value: formatNumber(latest.timestamp, 0), unit: "ms" },
          { label: "Chunk bytes", value: formatCanChunkBytes(latest.chunk) }
        ]
      : [
          { label: "Speed", value: formatNumber(latest?.speed, 1), unit: "source" },
          { label: "Throttle", value: formatPercent(latest?.throttle) },
          { label: "Brake", value: formatPercent(latest?.brake) },
          { label: "Steering", value: `${formatNumber(latest?.steering, 1)} deg` },
          { label: "Heading", value: `${formatNumber(latest?.heading, 1)} deg` },
          { label: "Gear", value: formatNumber(latest?.gear, 0) },
          { label: "Satellites", value: formatNumber(latest?.satellites, 0) },
          { label: "Trace", value: formatNumber(trace.length, 0), unit: "points" }
        ];

  return (
    <Box component="main" sx={{ minHeight: "100vh", px: { xs: 2, lg: 3 }, py: { xs: 2, lg: 3 } }}>
      <Box sx={{ width: "min(1320px, 100%)", mx: "auto" }}>
        <Stack
          direction={{ xs: "column", md: "row" }}
          alignItems={{ xs: "stretch", md: "center" }}
          justifyContent="space-between"
          spacing={2}
          sx={{ mb: 2 }}
        >
          <Stack direction="row" alignItems="center" spacing={1.5}>
            <SportsScoreIcon
              color="secondary"
              sx={{ fontSize: { xs: 34, sm: 42 }, flexShrink: 0, filter: "drop-shadow(0 0 18px rgba(255, 106, 0, 0.3))" }}
            />
            <Box>
              <Typography variant="h1" sx={{ fontSize: { xs: 28, sm: 38 }, lineHeight: 1 }}>
                ApexAI Telemetry
              </Typography>
              <Typography variant="caption" color="text.secondary" fontWeight={800}>
                {sourceLabel} - {sourceFile || "No source file selected"}
              </Typography>
            </Box>
          </Stack>
          <Stack direction={{ xs: "column", sm: "row" }} alignItems={{ xs: "stretch", sm: "center" }} spacing={1.5}>
            <Chip color={connection === "live" ? "success" : connection === "connecting" ? "warning" : "default"} label={connection} sx={{ fontWeight: 900, textTransform: "uppercase" }} />
            <Chip color="primary" label={sourceStatus} sx={{ fontWeight: 900 }} />
          </Stack>
        </Stack>

        <Card sx={{ mb: 1.5 }}>
          <CardContent sx={{ p: { xs: 1.5, md: 2 }, "&:last-child": { pb: { xs: 1.5, md: 2 } } }}>
            <Grid container spacing={1.25} alignItems="center">
              <Grid item xs={12} md={6}>
                <TextField
                  fullWidth
                  label="Server endpoint"
                  placeholder={`${DEFAULT_API_URL}/events/telemetry`}
                  value={apiUrl}
                  onChange={(event: ChangeEvent<HTMLInputElement>) => setApiUrl(event.target.value)}
                />
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <FormControl fullWidth size="small">
                  <InputLabel id="sensor-field-label">Sensor</InputLabel>
                  <Select
                    labelId="sensor-field-label"
                    label="Sensor"
                    value={sensorField}
                    onChange={(event) => setSensorField(event.target.value as SensorKey)}
                    disabled={state.source === "can"}
                  >
                    {SENSOR_OPTIONS.map((option) => (
                      <MenuItem key={option.key} value={option.key}>
                        {option.label}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <FormControl fullWidth size="small">
                  <InputLabel id="colormap-label">Colormap</InputLabel>
                  <Select
                    labelId="colormap-label"
                    label="Colormap"
                    value={colorMap}
                    onChange={(event) => setColorMap(event.target.value as ColorMapKey)}
                    disabled={state.source === "can"}
                  >
                    {COLORMAP_OPTIONS.map((option) => (
                      <MenuItem key={option.key} value={option.key}>
                        {option.label}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
            </Grid>
            <Divider sx={{ my: 1.5, borderColor: "rgba(255, 255, 255, 0.08)" }} />
            <Stack direction={{ xs: "column", sm: "row" }} flexWrap="wrap" gap={2} alignItems="center" justifyContent="space-between">
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" gap={1}>
                <Button
                  variant="contained"
                  color={state.status === "playing" ? "warning" : "success"}
                  onClick={handlePlayPause}
                  startIcon={state.status === "playing" ? <PauseIcon /> : <PlayArrowIcon />}
                  sx={{ fontWeight: 800, minWidth: 100 }}
                >
                  {state.status === "playing" ? "Pause" : "Play"}
                </Button>
                <Button
                  variant="outlined"
                  color="error"
                  onClick={handleStop}
                  startIcon={<StopIcon />}
                  sx={{ fontWeight: 800 }}
                >
                  Stop
                </Button>
                <Button
                  variant="outlined"
                  onClick={handleReset}
                  startIcon={<ReplayIcon />}
                  sx={{ fontWeight: 800 }}
                >
                  Reset
                </Button>
                <Button
                  variant={state.loop ? "contained" : "outlined"}
                  color={state.loop ? "primary" : "inherit"}
                  onClick={handleToggleLoop}
                  startIcon={<LoopIcon />}
                  sx={{ fontWeight: 800 }}
                >
                  Loop
                </Button>
              </Stack>
              
              <Stack direction="row" spacing={2} alignItems="center">
                <FormControl size="small" sx={{ minWidth: 100 }}>
                  <InputLabel id="speed-label">Speed</InputLabel>
                  <Select
                    labelId="speed-label"
                    label="Speed"
                    value={state.replay_speed}
                    onChange={(e) => handleChangeSpeed(Number(e.target.value))}
                  >
                    {[0.5, 1, 2, 5, 10].map((s) => (
                      <MenuItem key={s} value={s}>
                        {s}x
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                
                <FormControl size="small" sx={{ minWidth: 150 }}>
                  <InputLabel id="interval-label">Interval</InputLabel>
                  <Select
                    labelId="interval-label"
                    label="Interval"
                    value={state.stream_interval === null ? "source" : state.stream_interval}
                    onChange={(e) => handleChangeInterval(e.target.value === "source" ? null : Number(e.target.value))}
                  >
                    <MenuItem value="source">Source Timing</MenuItem>
                    <MenuItem value={0.1}>10 Hz (0.1s)</MenuItem>
                    <MenuItem value={0.2}>5 Hz (0.2s)</MenuItem>
                    <MenuItem value={0.5}>2 Hz (0.5s)</MenuItem>
                    <MenuItem value={1.0}>1 Hz (1.0s)</MenuItem>
                  </Select>
                </FormControl>
              </Stack>
            </Stack>
          </CardContent>
        </Card>

        <Card>
          <CardContent sx={{ p: { xs: 1.5, md: 2 }, "&:last-child": { pb: { xs: 1.5, md: 2 } } }}>
            <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" spacing={1.5} sx={{ mb: 1.5 }}>
              <Box>
                <Typography variant="overline" color="primary" fontWeight={900}>
                  Map
                </Typography>
                <Typography variant="h2" sx={{ fontSize: { xs: 22, md: 28 }, lineHeight: 1.1 }}>
                  {formatCoordinate(latest?.latitude, latest?.longitude)}
                </Typography>
              </Box>
              <Box sx={{ textAlign: { xs: "left", sm: "right" } }}>
                <Typography variant="overline" color="primary" fontWeight={900}>
                  Coloring
                </Typography>
                <Typography variant="h2" sx={{ fontSize: { xs: 22, md: 28 }, lineHeight: 1.1 }}>
                  {selectedSensor}
                </Typography>
                <Typography variant="caption" color="text.secondary" fontWeight={800}>
                  {formatRange(sensorRange, sensorField)}
                </Typography>
              </Box>
            </Stack>

            <TrackMap
              track={track}
              drivenTrack={drivenTrack}
              bounds={bounds}
              currentPoint={currentPoint}
              orientation={orientation}
              sensorField={sensorField}
              colorMap={colorMap}
              sensorRange={sensorRange}
              source={state.source ?? "vbo"}
            />
          </CardContent>
        </Card>

        <Grid container spacing={1.25} sx={{ mt: 1.5 }}>
          {sensorCards.map((metric) => (
            <Grid item xs={6} sm={4} lg={3} key={metric.label}>
              <Metric label={metric.label} value={metric.value} unit={metric.unit} />
            </Grid>
          ))}
        </Grid>
      </Box>
    </Box>
  );
}

const StaticTrack = memo(({
  track,
  bounds,
  sensorField,
  sensorRange,
  colorMap
}: {
  track: TrackPoint[];
  bounds: ReturnType<typeof trackBounds>;
  sensorField: SensorKey;
  colorMap: ColorMapKey;
  sensorRange: { min: number; max: number } | null;
}) => {
  const points = useMemo(() => track.map((point) => projectPoint(point, bounds)).join(" "), [track, bounds]);
  const start = useMemo(() => track[0] ? projectPoint(track[0], bounds).split(",").map(Number) : null, [track, bounds]);
  const finish = useMemo(() => track.length > 1 ? projectPoint(track[track.length - 1], bounds).split(",").map(Number) : null, [track, bounds]);
  const segments = useMemo(() => buildColoredSegments(track, bounds, sensorField, sensorRange, colorMap), [track, bounds, sensorField, sensorRange, colorMap]);
  const legendStops = useMemo(() => [0, 0.25, 0.5, 0.75, 1].map((stop) => colorForStop(stop, colorMap, sensorField)).join(", "), [colorMap, sensorField]);

  return (
    <>
      {points ? <polyline points={points} fill="none" stroke="#3a3d43" opacity="0.82" strokeLinecap="round" strokeLinejoin="round" strokeWidth="12" /> : null}
      {segments.length > 0 ? (
        segments.map((segment) => (
          <line
            key={segment.key}
            x1={segment.x1}
            y1={segment.y1}
            x2={segment.x2}
            y2={segment.y2}
            stroke={segment.color}
            strokeLinecap="round"
            strokeWidth="5"
            opacity="0.96"
            filter="url(#trackGlow)"
          />
        ))
      ) : points ? (
        <polyline points={points} fill="none" stroke="#d9d9d9" opacity="0.92" strokeLinecap="round" strokeLinejoin="round" strokeWidth="4" />
      ) : null}
      {start ? <MapEndpointMarker x={start[0]} y={start[1]} label="S" fill="#62e6bc" /> : null}
      {finish ? <MapEndpointMarker x={finish[0]} y={finish[1]} label="F" fill="#ff6a00" /> : null}
      {sensorRange ? (
        <g transform="translate(38 610)">
          <rect x="0" y="0" width="260" height="36" rx="6" fill="rgba(0, 0, 0, 0.58)" stroke="rgba(255, 255, 255, 0.16)" />
          <foreignObject x="14" y="10" width="140" height="12">
            <div className="mapLegend" style={{ background: `linear-gradient(90deg, ${legendStops})` }} />
          </foreignObject>
          <text x="14" y="29" className="mapLegendText">
            {formatSensorValue(sensorRange.min, sensorField)}
          </text>
          <text x="246" y="29" textAnchor="end" className="mapLegendText">
            {formatSensorValue(sensorRange.max, sensorField)}
          </text>
        </g>
      ) : null}
    </>
  );
});
StaticTrack.displayName = "StaticTrack";

function TrackMap({
  track,
  drivenTrack,
  bounds,
  currentPoint,
  orientation,
  sensorField,
  colorMap,
  sensorRange,
  source
}: {
  track: TrackPoint[];
  drivenTrack: TrackPoint[];
  bounds: ReturnType<typeof trackBounds>;
  currentPoint: TrackPoint | null;
  orientation: number | null;
  sensorField: SensorKey;
  colorMap: ColorMapKey;
  sensorRange: { min: number; max: number } | null;
  source: "vbo" | "can";
}) {
  const drivenPoints = useMemo(() => drivenTrack.map((point) => projectPoint(point, bounds)).join(" "), [drivenTrack, bounds]);
  const current = currentPoint ? projectPoint(currentPoint, bounds).split(",").map(Number) : null;
  const emptyMessage = source === "can" ? "CAN raw chunks are streaming without decoded GPS" : "Waiting for GPS telemetry";

  return (
    <svg className="trackMap" viewBox="0 0 1000 680" role="img" aria-label="Top view race map">
      <defs>
        <linearGradient id="satelliteFade" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#111625" />
          <stop offset="45%" stopColor="#162030" />
          <stop offset="100%" stopColor="#060912" />
        </linearGradient>
        <radialGradient id="mapVignette" cx="52%" cy="45%" r="68%">
          <stop offset="0%" stopColor="rgba(114, 244, 255, 0.08)" />
          <stop offset="68%" stopColor="rgba(0, 0, 0, 0)" />
          <stop offset="100%" stopColor="rgba(0, 0, 0, 0.5)" />
        </radialGradient>
        <pattern id="grid" width="50" height="50" patternUnits="userSpaceOnUse">
          <path d="M 50 0 L 0 0 0 50" fill="none" stroke="rgba(255, 255, 255, 0.045)" strokeWidth="1" />
        </pattern>
        <filter id="trackGlow" x="-10%" y="-10%" width="120%" height="120%">
          <feDropShadow dx="0" dy="0" stdDeviation="3" floodColor="#72f4ff" floodOpacity="0.32" />
        </filter>
        <filter id="vehicleShadow" x="-50%" y="-50%" width="200%" height="200%">
          <feDropShadow dx="0" dy="4" stdDeviation="4" floodColor="#000000" floodOpacity="0.62" />
          <feDropShadow dx="0" dy="0" stdDeviation="5" floodColor="#72f4ff" floodOpacity="0.35" />
        </filter>
      </defs>
      <rect width="1000" height="680" rx="8" fill="url(#satelliteFade)" />
      <path d="M -40 140 C 120 88 208 172 334 118 C 482 54 618 84 1050 6" fill="none" stroke="#26354a" strokeWidth="54" opacity="0.28" />
      <path d="M -60 536 C 116 462 206 566 348 486 C 492 406 612 416 1058 318" fill="none" stroke="#1c2536" strokeWidth="42" opacity="0.32" />
      <path d="M 724 -40 C 672 136 746 246 684 376 C 626 496 682 574 630 722" fill="none" stroke="#162030" strokeWidth="68" opacity="0.32" />
      <path d="M 12 210 C 170 176 256 242 390 204 C 544 160 678 160 1008 74" fill="none" stroke="#7a8a99" strokeWidth="2" opacity="0.18" />
      <path d="M 0 452 C 178 392 298 426 446 360 C 604 290 740 300 1000 238" fill="none" stroke="#637381" strokeWidth="2" opacity="0.16" />
      <rect width="1000" height="680" rx="8" fill="url(#mapVignette)" />
      <rect width="1000" height="680" rx="8" fill="url(#grid)" />
      
      <StaticTrack
        track={track}
        bounds={bounds}
        sensorField={sensorField}
        sensorRange={sensorRange}
        colorMap={colorMap}
      />

      {drivenPoints ? <polyline points={drivenPoints} fill="none" stroke="#72f4ff" strokeLinecap="round" strokeLinejoin="round" strokeWidth="5" filter="url(#trackGlow)" /> : null}
      
      {current ? (
        <VehicleMarker x={current[0]} y={current[1]} orientation={orientation ?? 0} />
      ) : (
        <text x="500" y="340" textAnchor="middle" className="emptyMap">
          {emptyMessage}
        </text>
      )}
    </svg>
  );
}

function MapEndpointMarker({ x, y, label, fill }: { x: number; y: number; label: string; fill: string }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <circle r="14" fill={fill} opacity="0.98" stroke="#ffffff" strokeWidth="2" filter="url(#vehicleShadow)" />
      <text y="5" textAnchor="middle" className="mapMarkerText">
        {label}
      </text>
    </g>
  );
}

function VehicleMarker({ x, y, orientation }: { x: number; y: number; orientation: number }) {
  return (
    <g transform={`translate(${x} ${y}) rotate(${orientation})`} filter="url(#vehicleShadow)">
      <path d="M 0 -30 L 20 24 L 0 14 L -20 24 Z" fill="#f8f8f8" stroke="#09090b" strokeWidth="3" strokeLinejoin="round" />
      <path d="M 0 -18 L 8 13 L 0 9 L -8 13 Z" fill="#15161a" opacity="0.94" />
      <circle cx="0" cy="0" r="5" fill="#72f4ff" stroke="#09090b" strokeWidth="2" />
    </g>
  );
}

function Metric({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <Card variant="outlined" sx={{ height: "100%", bgcolor: "rgba(3, 5, 8, 0.5)", boxShadow: "none" }}>
      <CardContent sx={{ minHeight: 82, p: 1.5, display: "grid", alignContent: "center", gap: 0.5, "&:last-child": { pb: 1.5 } }}>
        <Typography variant="caption" color="text.secondary" fontWeight={900} textTransform="uppercase">
          {label}
        </Typography>
        <Typography variant="h6" sx={{ fontWeight: 900, lineHeight: 1.05, overflowWrap: "anywhere" }}>
          {value}
        </Typography>
        {unit ? (
          <Typography variant="caption" color="text.secondary" fontWeight={800}>
            {unit}
          </Typography>
        ) : null}
      </CardContent>
    </Card>
  );
}

async function fetchJson<T>(url: string) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

async function postJson<T>(url: string, body?: unknown) {
  const response = await fetch(url, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

function normalizeEndpoint(value: string) {
  let cleaned = value.trim().replace(/\/$/, "");
  if (cleaned.endsWith("/events/telemetry")) {
    cleaned = cleaned.slice(0, -"/events/telemetry".length);
  }
  return cleaned;
}

function buildTrack(
  samples: Array<TelemetryPacket | TraceSample>,
  fixedOrigin?: TrackPoint | null,
  maxPoints?: number
): TrackPoint[] {
  const gps = samples.filter(hasGps);
  if (gps.length === 0) {
    return [];
  }

  let selectedGps = gps;
  if (maxPoints && gps.length > maxPoints) {
    const keepEvery = Math.max(2, Math.floor(gps.length / maxPoints));
    selectedGps = [];
    selectedGps.push(gps[0]);
    for (let i = 1; i < gps.length - 1; i++) {
      if (i % keepEvery === 0) {
        selectedGps.push(gps[i]);
      }
    }
    selectedGps.push(gps[gps.length - 1]);
  }

  const origin = fixedOrigin ?? selectedGps[0];
  return selectedGps.map((packet) => {
    const projected = metersFromOrigin(origin.latitude, origin.longitude, packet.latitude, packet.longitude);
    return {
      sequence: packet.sequence,
      timestamp: packet.timestamp,
      latitude: packet.latitude,
      longitude: packet.longitude,
      heading: packet.heading ?? null,
      speed: packet.speed ?? null,
      throttle: packet.throttle ?? null,
      brake: packet.brake ?? null,
      steering: packet.steering ?? null,
      altitude: packet.altitude ?? null,
      satellites: packet.satellites ?? null,
      gear: packet.gear ?? null,
      ...projected
    };
  });
}

function projectPacketFromOrigin(packet: TelemetryPacket | null, origin: TrackPoint | null): TrackPoint | null {
  if (!packet || !origin || typeof packet.latitude !== "number" || typeof packet.longitude !== "number") {
    return null;
  }
  const projected = metersFromOrigin(origin.latitude, origin.longitude, packet.latitude, packet.longitude);
  return {
    sequence: packet.sequence,
    timestamp: packet.timestamp,
    latitude: packet.latitude,
    longitude: packet.longitude,
    heading: packet.heading ?? null,
    speed: packet.speed ?? null,
    throttle: packet.throttle ?? null,
    brake: packet.brake ?? null,
    steering: packet.steering ?? null,
    altitude: packet.altitude ?? null,
    satellites: packet.satellites ?? null,
    gear: packet.gear ?? null,
    ...projected
  };
}

function hasGps(packet: TelemetryPacket | TraceSample): packet is (TelemetryPacket | TraceSample) & { latitude: number; longitude: number } {
  return typeof packet.latitude === "number" && typeof packet.longitude === "number";
}

function metersFromOrigin(originLat: number, originLon: number, lat: number, lon: number) {
  const metersPerDegreeLat = 111_320;
  const metersPerDegreeLon = metersPerDegreeLat * Math.cos(toRadians(originLat));
  return {
    xMeters: (lon - originLon) * metersPerDegreeLon,
    yMeters: (lat - originLat) * metersPerDegreeLat
  };
}

function computeOrientation(packet: TelemetryPacket | null) {
  return packet?.heading !== null && packet?.heading !== undefined ? normalizeAngle(packet.heading) : null;
}

function trackBounds(track: TrackPoint[]) {
  if (track.length === 0) {
    return { minX: -50, maxX: 50, minY: -50, maxY: 50 };
  }
  const xs = track.map((point) => point.xMeters);
  const ys = track.map((point) => point.yMeters);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const padX = Math.max(20, (maxX - minX) * 0.12);
  const padY = Math.max(20, (maxY - minY) * 0.12);
  return { minX: minX - padX, maxX: maxX + padX, minY: minY - padY, maxY: maxY + padY };
}

function projectPoint(point: TrackPoint, bounds: ReturnType<typeof trackBounds>) {
  const width = bounds.maxX - bounds.minX || 1;
  const height = bounds.maxY - bounds.minY || 1;
  const x = ((point.xMeters - bounds.minX) / width) * 880 + 60;
  const y = 620 - ((point.yMeters - bounds.minY) / height) * 560;
  return `${x},${y}`;
}

function buildColoredSegments(
  track: TrackPoint[],
  bounds: ReturnType<typeof trackBounds>,
  sensorField: SensorKey,
  sensorRange: { min: number; max: number } | null,
  colorMap: ColorMapKey
) {
  if (!sensorRange || track.length < 2) {
    return [];
  }
  return track.slice(1).map((point, index) => {
    const previous = track[index];
    const [x1, y1] = projectPoint(previous, bounds).split(",").map(Number);
    const [x2, y2] = projectPoint(point, bounds).split(",").map(Number);
    const value = numberOrNull(point[sensorField]) ?? numberOrNull(previous[sensorField]) ?? sensorRange.min;
    return {
      key: `${previous.sequence}-${point.sequence}`,
      x1,
      y1,
      x2,
      y2,
      color: colorForValue(value, sensorRange, colorMap, sensorField)
    };
  });
}

function dataRange(track: TrackPoint[], sensorField: SensorKey) {
  const values = track.map((point) => numberOrNull(point[sensorField])).filter((value): value is number => value !== null);
  if (values.length === 0) {
    return null;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) {
    return { min: min - 1, max: max + 1 };
  }
  return { min, max };
}

function colorForValue(value: number, range: { min: number; max: number }, colorMap: ColorMapKey, sensorField: SensorKey) {
  const stop = (value - range.min) / (range.max - range.min || 1);
  return colorForStop(stop, colorMap, sensorField);
}

function colorForStop(stop: number, colorMap: ColorMapKey, sensorField: SensorKey = "speed") {
  if (colorMap === "apex") {
    return apexSensorColor(stop, sensorField);
  }
  const palettes: Record<ColorMapKey, string[]> = {
    apex: ["#72f4ff", "#62e6bc", "#ffb300", "#ff6a00", "#ff3d4d"],
    turbo: ["#30123b", "#466be3", "#22c4b7", "#a4fc3c", "#f98c10", "#b40019"],
    viridis: ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"],
    magma: ["#000004", "#3b0f70", "#8c2981", "#de4968", "#fe9f6d", "#fcfdbf"],
    icefire: ["#003f5c", "#2f8f9d", "#f7f7f7", "#f29e4c", "#9a031e"]
  };
  const palette = palettes[colorMap];
  const clamped = Math.max(0, Math.min(1, stop));
  const scaled = clamped * (palette.length - 1);
  const left = Math.floor(scaled);
  const right = Math.min(palette.length - 1, left + 1);
  return mixHex(palette[left], palette[right], scaled - left);
}

function apexSensorColor(stop: number, sensorField: SensorKey) {
  const clamped = Math.max(0, Math.min(1, stop));
  const sensorPalettes: Record<SensorKey, string[]> = {
    speed: ["#72f4ff", "#62e6bc", "#ffb300", "#ff6a00", "#ff3d4d"],
    throttle: ["rgba(255, 255, 255, 0.24)", "#2f7d66", "#62e6bc"],
    brake: ["rgba(255, 255, 255, 0.22)", "#8f2630", "#ff3d4d"],
    steering: ["#72f4ff", "#f7f4ea", "#ff6a00"],
    heading: ["#72f4ff", "#62e6bc", "#ffb300", "#ff6a00"],
    altitude: ["#060912", "#26354a", "#72f4ff"],
    satellites: ["#ff3d4d", "#ffb300", "#62e6bc"],
    gear: ["#72f4ff", "#f7f4ea", "#ff6a00"]
  };
  const palette = sensorPalettes[sensorField];
  const scaled = clamped * (palette.length - 1);
  const left = Math.floor(scaled);
  const right = Math.min(palette.length - 1, left + 1);
  return mixCssColor(palette[left], palette[right], scaled - left);
}

function mixCssColor(left: string, right: string, amount: number) {
  if (left.startsWith("rgba") || right.startsWith("rgba")) {
    return amount < 0.5 ? left : right;
  }
  return mixHex(left, right, amount);
}

function mixHex(left: string, right: string, amount: number) {
  const l = parseHex(left);
  const r = parseHex(right);
  const mixed = l.map((value, index) => Math.round(value + (r[index] - value) * amount));
  return `rgb(${mixed[0]}, ${mixed[1]}, ${mixed[2]})`;
}

function parseHex(value: string) {
  const clean = value.replace("#", "");
  return [0, 2, 4].map((index) => parseInt(clean.slice(index, index + 2), 16));
}

function numberOrNull(value: unknown) {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatCanChunkBytes(chunk?: string) {
  if (!chunk) {
    return "--";
  }
  return formatNumber(chunk.split(/\s+/).filter(Boolean).length, 0);
}

function rawPacketRows(packet: TelemetryPacket | null): Array<[string, unknown]> {
  if (!packet) {
    return [];
  }
  if (packet.source === "can") {
    return [
      ["source", "can"],
      ["timestamp_ms", packet.timestamp],
      ["line", packet.line],
      ["chunk", packet.chunk]
    ];
  }
  return Object.entries(packet.raw ?? {});
}

function selectedSensorLabel(sensorField: SensorKey) {
  return SENSOR_OPTIONS.find((option) => option.key === sensorField)?.label ?? sensorField;
}

function formatRange(range: { min: number; max: number } | null, sensorField: SensorKey) {
  if (!range) {
    return "No trace data";
  }
  return `${formatSensorValue(range.min, sensorField)} to ${formatSensorValue(range.max, sensorField)}`;
}

function formatSensorValue(value: number, sensorField: SensorKey) {
  const option = SENSOR_OPTIONS.find((candidate) => candidate.key === sensorField);
  const digits = sensorField === "gear" || sensorField === "satellites" ? 0 : 1;
  const unit = option?.unit && option.unit !== "source" ? ` ${option.unit}` : "";
  return `${formatNumber(value, digits)}${unit}`;
}

function formatCoordinate(lat?: number | null, lon?: number | null) {
  if (lat === null || lat === undefined || lon === null || lon === undefined) {
    return "No GPS lock";
  }
  return `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
}

function formatPercent(value?: number | null) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "--";
  }
  const normalized = value > 1 ? value : value * 100;
  return `${normalized.toFixed(0)}%`;
}

function formatNumber(value?: number | null, digits = 1) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "--";
  }
  return value.toFixed(digits);
}

function normalizeAngle(angle: number) {
  return ((angle % 360) + 360) % 360;
}

function toRadians(value: number) {
  return (value * Math.PI) / 180;
}
