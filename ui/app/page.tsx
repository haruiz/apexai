"use client";

import PauseIcon from "@mui/icons-material/Pause";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import SportsScoreIcon from "@mui/icons-material/SportsScore";
import StopIcon from "@mui/icons-material/Stop";
import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  Grid,
  IconButton,
  InputAdornment,
  LinearProgress,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableRow,
  TextField,
  Typography
} from "@mui/material";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChangeEvent, FormEvent, useEffect, useMemo, useRef } from "react";
import { ReplayState, TelemetryPacket, useTelemetryStore } from "./store";

type TrackPoint = {
  sequence: number;
  timestamp: number;
  latitude: number;
  longitude: number;
  heading: number | null;
  xMeters: number;
  yMeters: number;
};

type TraceSample = {
  sequence: number;
  timestamp: number;
  latitude: number;
  longitude: number;
  heading: number | null;
};

const DEFAULT_STATE: ReplayState = {
  status: "idle",
  current_index: 0,
  total_samples: 0,
  replay_speed: 1,
  stream_interval: null,
  loop: false,
  vbo_file: ""
};
const DEFAULT_API_URL = "http://localhost:8000";
const RAY_SPACING_METERS = 8;
const iconButtonSx = {
  width: "100%",
  minHeight: 44,
  border: "1px solid",
  borderColor: "divider",
  borderRadius: 1,
  bgcolor: "rgba(0, 0, 0, 0.36)",
  "&:hover": {
    bgcolor: "action.hover",
    borderColor: "primary.main"
  }
};

export default function Home() {
  const queryClient = useQueryClient();
  const reconnectRef = useRef<number | null>(null);
  const initialReplayStateSyncedRef = useRef(false);
  const {
    apiUrl,
    connection,
    latest,
    history,
    frequencyHz,
    replaySpeed,
    rayPointCount,
    vehicleIconUrl,
    timingDirty,
    setApiUrl,
    setConnection,
    setTelemetryActive,
    setFrequencyHz,
    setReplaySpeed,
    setRayPointCount,
    setVehicleIconUrl,
    syncTiming,
    acceptTiming,
    resetTelemetry,
    pushPacket
  } = useTelemetryStore();

  const endpoint = useMemo(() => normalizeEndpoint(apiUrl), [apiUrl]);

  const stateQuery = useQuery({
    queryKey: ["replay-state", endpoint],
    queryFn: () => fetchJson<ReplayState>(`${endpoint}/state`),
    enabled: Boolean(endpoint),
    refetchInterval: 1000
  });

  const latestQuery = useQuery({
    queryKey: ["latest-telemetry", endpoint],
    queryFn: () => fetchJson<TelemetryPacket | null>(`${endpoint}/telemetry/latest`),
    enabled: Boolean(endpoint)
  });

  const traceQuery = useQuery({
    queryKey: ["telemetry-trace", endpoint],
    queryFn: () => fetchJson<TraceSample[]>(`${endpoint}/telemetry/trace`),
    enabled: Boolean(endpoint),
    staleTime: Infinity
  });

  const state = stateQuery.data ?? DEFAULT_STATE;

  useEffect(() => {
    const origin = window.location.origin;
    const isNextDev = window.location.port === "3000";
    setApiUrl(process.env.NEXT_PUBLIC_APEXAI_API_URL ?? (isNextDev ? DEFAULT_API_URL : origin));
  }, [setApiUrl]);

  useEffect(() => {
    if (stateQuery.data) {
      syncTiming(stateQuery.data.stream_interval, stateQuery.data.replay_speed);
      if (!initialReplayStateSyncedRef.current) {
        setTelemetryActive(stateQuery.data.status === "playing");
        initialReplayStateSyncedRef.current = true;
      }
    }
  }, [setTelemetryActive, stateQuery.data, syncTiming]);

  useEffect(() => {
    if (latestQuery.data) {
      pushPacket(latestQuery.data);
    }
  }, [latestQuery.data, pushPacket]);

  useEffect(() => {
    if (endpoint && state.vbo_file) {
      queryClient.invalidateQueries({ queryKey: ["telemetry-trace", endpoint] });
    }
  }, [endpoint, queryClient, state.vbo_file]);

  useEffect(() => {
    if (!endpoint) {
      return;
    }

    let closed = false;

    function connect() {
      if (closed) {
        return;
      }
      setConnection("connecting");
      const socket = new WebSocket(toWebSocketUrl(endpoint, "/ws/telemetry"));

      socket.onopen = () => setConnection("live");
      socket.onmessage = (event) => {
        if (!useTelemetryStore.getState().telemetryActive) {
          return;
        }
        const packet = JSON.parse(event.data) as TelemetryPacket;
        pushPacket(packet);
      };
      socket.onclose = () => {
        if (closed) {
          return;
        }
        setConnection("offline");
        reconnectRef.current = window.setTimeout(connect, 1500);
      };
      socket.onerror = () => socket.close();
    }

    connect();

    return () => {
      closed = true;
      if (reconnectRef.current) {
        window.clearTimeout(reconnectRef.current);
      }
    };
  }, [endpoint, pushPacket, setConnection]);

  const trace = traceQuery.data ?? [];
  const track = useMemo(() => buildTrack(trace), [trace]);
  const traceOrigin = track[0] ?? null;
  const drivenTrack = useMemo(() => buildTrack(history, traceOrigin), [history, traceOrigin]);
  const projectionOrigin = traceOrigin ?? drivenTrack[0] ?? null;
  const currentPoint = useMemo(() => projectPacketFromOrigin(latest, projectionOrigin), [latest, projectionOrigin]);
  const orientation = useMemo(() => computeOrientation(history), [history]);
  const rayPoints = useMemo(() => buildRayPoints(currentPoint, orientation, Number(rayPointCount)), [currentPoint, orientation, rayPointCount]);
  const bounds = useMemo(() => trackBounds([...(track.length > 0 ? track : drivenTrack), ...rayPoints]), [track, drivenTrack, rayPoints]);
  const progress = state.total_samples > 0 ? Math.min(100, (state.current_index / state.total_samples) * 100) : 0;

  async function control(path: string, body?: unknown) {
    if (path === "/replay/start") {
      setTelemetryActive(true);
    }
    if (path === "/replay/pause" || path === "/replay/reset" || path === "/replay/stop") {
      setTelemetryActive(false);
    }
    if (path === "/replay/reset" || path === "/replay/stop") {
      resetTelemetry();
      queryClient.setQueryData(["latest-telemetry", endpoint], null);
    }
    const nextState = await postJson<ReplayState>(`${endpoint}${path}`, body);
    queryClient.setQueryData(["replay-state", endpoint], nextState);
    if (path === "/replay/speed" || path === "/replay/stream-interval") {
      acceptTiming(nextState.stream_interval, nextState.replay_speed);
    } else {
      syncTiming(nextState.stream_interval, nextState.replay_speed);
    }
    if (path === "/replay/reset" || path === "/replay/stop") {
      queryClient.invalidateQueries({ queryKey: ["telemetry-trace", endpoint] });
    }
  }

  async function applyTimingUpdates() {
    const speed = Number(replaySpeed);
    const hz = Number(frequencyHz);
    if (Number.isFinite(speed) && speed > 0) {
      await control("/replay/speed", { speed });
    }
    if (Number.isFinite(hz) && hz > 0) {
      await control("/replay/stream-interval", { seconds: 1 / hz });
    }
  }

  async function applyTiming(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await applyTimingUpdates();
  }

  async function startReplay() {
    if (timingDirty) {
      await applyTimingUpdates();
    }
    await control("/replay/start");
  }

  return (
    <Box component="main" sx={{ minHeight: "100vh", px: { xs: 2, lg: 3 }, py: 3 }}>
      <Box sx={{ width: "min(1500px, 100%)", mx: "auto" }}>
        <Stack
          direction={{ xs: "column", md: "row" }}
          alignItems={{ xs: "stretch", md: "flex-end" }}
          justifyContent="space-between"
          spacing={3}
          sx={{ mb: 2.5 }}
        >
          <Box>
            <Stack direction="row" alignItems="center" spacing={{ xs: 1.25, sm: 2 }}>
              <SportsScoreIcon
                color="primary"
                sx={{
                  fontSize: { xs: 42, sm: 62, lg: 76 },
                  flexShrink: 0,
                  filter: "drop-shadow(0 0 18px rgba(255, 31, 61, 0.34))"
                }}
              />
              <Typography variant="h1" sx={{ fontSize: { xs: 48, sm: 72, lg: 88 }, lineHeight: 0.95 }}>
                ApexAI Telemetry Dashboard
              </Typography>
            </Stack>
          </Box>
          <Stack direction={{ xs: "column", sm: "row" }} alignItems={{ xs: "stretch", sm: "center" }} spacing={1.5}>
            <TextField
              label="Server"
              placeholder={DEFAULT_API_URL}
              value={apiUrl}
              onChange={(event: ChangeEvent<HTMLInputElement>) => setApiUrl(event.target.value)}
              sx={{ width: { xs: "100%", sm: 430 } }}
            />
            <Chip color={connection === "live" ? "success" : connection === "connecting" ? "warning" : "default"} label={connection} sx={{ fontWeight: 900, textTransform: "uppercase" }} />
          </Stack>
        </Stack>

        <Grid container spacing={2.25} alignItems="flex-start">
          <Grid item xs={12} lg={8.8}>
            <Card>
              <CardContent sx={{ p: { xs: 2, md: 2.25 }, "&:last-child": { pb: { xs: 2, md: 2.25 } } }}>
                <Stack direction={{ xs: "column", sm: "row" }} alignItems={{ xs: "flex-start", sm: "flex-start" }} justifyContent="space-between" spacing={2} sx={{ mb: 2 }}>
                  <Box>
                    <Typography variant="overline" color="primary" fontWeight={900}>
                      Top view
                    </Typography>
                    <Typography variant="h2" sx={{ fontSize: { xs: 24, md: 32 }, lineHeight: 1.1 }}>
                      {formatCoordinate(latest?.latitude, latest?.longitude)}
                    </Typography>
                  </Box>
                  <Box sx={{ textAlign: { xs: "left", sm: "right" } }}>
                    <Typography variant="h2" sx={{ fontSize: 32, lineHeight: 1 }}>
                      {formatNumber(orientation, 1)} deg
                    </Typography>
                    <Typography variant="caption" color="text.secondary" fontWeight={800}>
                      orientation
                    </Typography>
                  </Box>
                </Stack>

                <TrackMap
                  track={track}
                  drivenTrack={drivenTrack}
                  rayPoints={rayPoints}
                  bounds={bounds}
                  currentPoint={currentPoint}
                  orientation={orientation}
                  vehicleIconUrl={vehicleIconUrl}
                />

                <Grid container spacing={1.25} sx={{ mt: 0.25 }}>
                  <Grid item xs={6} sm={4} md>
                    <Metric label="Trace points" value={traceQuery.isError ? "Not loaded" : formatNumber(trace.length, 0)} />
                  </Grid>
                  <Grid item xs={6} sm={4} md>
                    <Metric label="X position" value={`${formatNumber(currentPoint?.xMeters, 1)} m`} />
                  </Grid>
                  <Grid item xs={6} sm={4} md>
                    <Metric label="Y position" value={`${formatNumber(currentPoint?.yMeters, 1)} m`} />
                  </Grid>
                  <Grid item xs={6} sm={4} md>
                    <Metric label="Speed" value={`${formatNumber(latest?.speed, 1)}`} unit="source" />
                  </Grid>
                  <Grid item xs={6} sm={4} md>
                    <Metric label="Heading" value={`${formatNumber(latest?.heading, 1)} deg`} />
                  </Grid>
                  <Grid item xs={6} sm={4} md>
                    <Metric label="Ray length" value={`${formatNumber(rayPoints.length * RAY_SPACING_METERS, 0)} m`} />
                  </Grid>
                </Grid>
              </CardContent>
            </Card>
          </Grid>

          <Grid item xs={12} lg={3.2}>
            <Stack spacing={1.5}>
              <Card>
                <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
                  <Stack direction="row" alignItems="flex-start" justifyContent="space-between" spacing={2}>
                    <Box>
                      <Typography variant="overline" color="primary" fontWeight={900}>
                        Replay
                      </Typography>
                      <Typography variant="h2" sx={{ fontSize: 28, textTransform: "capitalize" }}>
                        {state.status}
                      </Typography>
                    </Box>
                    <Typography variant="caption" color="text.secondary" fontWeight={900}>
                      {state.current_index} / {state.total_samples}
                    </Typography>
                  </Stack>

                  <LinearProgress
                    variant="determinate"
                    value={progress}
                    sx={{
                      my: 2,
                      height: 9,
                      borderRadius: 999,
                      bgcolor: "rgba(255, 255, 255, 0.1)",
                      "& .MuiLinearProgress-bar": {
                        bgcolor: "primary.main",
                        backgroundImage: "linear-gradient(90deg, #b40019, #ff1f3d, #ff6b7c)"
                      }
                    }}
                  />

                  <Grid container spacing={1}>
                    <Grid item xs={3}>
                      <IconButton color="primary" aria-label="Start replay" onClick={startReplay} sx={iconButtonSx}>
                        <PlayArrowIcon />
                      </IconButton>
                    </Grid>
                    <Grid item xs={3}>
                      <IconButton aria-label="Pause replay" onClick={() => control("/replay/pause")} sx={iconButtonSx}>
                        <PauseIcon />
                      </IconButton>
                    </Grid>
                    <Grid item xs={3}>
                      <IconButton color="primary" aria-label="Reset replay" onClick={() => control("/replay/reset")} sx={iconButtonSx}>
                        <RestartAltIcon />
                      </IconButton>
                    </Grid>
                    <Grid item xs={3}>
                      <IconButton color="error" aria-label="Stop replay" onClick={() => control("/replay/stop")} sx={iconButtonSx}>
                        <StopIcon />
                      </IconButton>
                    </Grid>
                  </Grid>

                  <Box component="form" onSubmit={applyTiming} sx={{ mt: 2 }}>
                    <Grid container spacing={1} alignItems="flex-end">
                      <Grid item xs={4}>
                        <TextField
                          fullWidth
                          label="Frequency"
                          inputMode="decimal"
                          type="number"
                          value={frequencyHz}
                          onChange={(event: ChangeEvent<HTMLInputElement>) => setFrequencyHz(event.target.value)}
                          inputProps={{ min: 0.01, step: 0.01 }}
                          InputProps={{ endAdornment: <InputAdornment position="end">Hz</InputAdornment> }}
                        />
                      </Grid>
                      <Grid item xs={3}>
                        <TextField
                          fullWidth
                          label="Speed"
                          inputMode="decimal"
                          type="number"
                          value={replaySpeed}
                          onChange={(event: ChangeEvent<HTMLInputElement>) => setReplaySpeed(event.target.value)}
                          inputProps={{ min: 0.01, step: 0.01 }}
                          InputProps={{ endAdornment: <InputAdornment position="end">x</InputAdornment> }}
                        />
                      </Grid>
                      <Grid item xs={3}>
                        <TextField
                          fullWidth
                          label="Ray points"
                          inputMode="numeric"
                          type="number"
                          value={rayPointCount}
                          onChange={(event: ChangeEvent<HTMLInputElement>) => setRayPointCount(event.target.value)}
                          inputProps={{ min: 0, max: 60, step: 1 }}
                        />
                      </Grid>
                      <Grid item xs={2}>
                        <Button fullWidth variant="contained" type="submit">
                          Apply
                        </Button>
                      </Grid>
                      <Grid item xs={12}>
                        <TextField
                          fullWidth
                          label="Vehicle SVG"
                          placeholder="/car.svg"
                          value={vehicleIconUrl}
                          onChange={(event: ChangeEvent<HTMLInputElement>) => setVehicleIconUrl(event.target.value)}
                        />
                      </Grid>
                    </Grid>
                  </Box>
                </CardContent>
              </Card>

              <Grid container spacing={1.25}>
                {[
                  ["Throttle", formatPercent(latest?.throttle)],
                  ["Brake", formatPercent(latest?.brake)],
                  ["Steering", `${formatNumber(latest?.steering, 1)} deg`],
                  ["Gear", formatNumber(latest?.gear, 0)],
                  ["Lap", formatNumber(latest?.lap, 0)],
                  ["Satellites", formatNumber(latest?.satellites, 0)]
                ].map(([label, value]) => (
                  <Grid item xs={6} key={label}>
                    <Metric label={label} value={value} />
                  </Grid>
                ))}
              </Grid>

              <Card>
                <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
                  <Stack direction="row" alignItems="flex-start" justifyContent="space-between" spacing={2}>
                    <Box>
                      <Typography variant="overline" color="primary" fontWeight={900}>
                        Sensors
                      </Typography>
                      <Typography variant="h2" sx={{ fontSize: 26 }}>
                        Raw packet
                      </Typography>
                    </Box>
                    <Typography variant="caption" color="text.secondary" fontWeight={900}>
                      #{latest?.sequence ?? 0}
                    </Typography>
                  </Stack>
                  <Divider sx={{ my: 1.5 }} />
                  <TableContainer sx={{ maxHeight: 350, border: "1px solid rgba(255, 255, 255, 0.12)", borderRadius: 1, bgcolor: "background.paper" }}>
                    <Table stickyHeader size="small">
                      <TableBody>
                        {Object.entries(latest?.raw ?? {})
                          .slice(0, 28)
                          .map(([key, value]) => (
                            <TableRow key={key} hover>
                              <TableCell sx={{ color: "text.secondary", fontWeight: 900, width: "42%", wordBreak: "break-word" }}>{key}</TableCell>
                              <TableCell sx={{ fontWeight: 700, wordBreak: "break-word" }}>{String(value ?? "")}</TableCell>
                            </TableRow>
                          ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </CardContent>
              </Card>
            </Stack>
          </Grid>
        </Grid>
      </Box>
    </Box>
  );
}

function TrackMap({
  track,
  drivenTrack,
  rayPoints,
  bounds,
  currentPoint,
  orientation,
  vehicleIconUrl
}: {
  track: TrackPoint[];
  drivenTrack: TrackPoint[];
  rayPoints: TrackPoint[];
  bounds: ReturnType<typeof trackBounds>;
  currentPoint: TrackPoint | null;
  orientation: number | null;
  vehicleIconUrl: string;
}) {
  const points = track.map((point) => projectPoint(point, bounds)).join(" ");
  const drivenPoints = drivenTrack.map((point) => projectPoint(point, bounds)).join(" ");
  const rayPolyline = rayPoints.map((point) => projectPoint(point, bounds)).join(" ");
  const current = currentPoint ? projectPoint(currentPoint, bounds).split(",").map(Number) : null;

  return (
    <svg className="trackMap" viewBox="0 0 1000 680" role="img" aria-label="Top view race map">
      <defs>
        <pattern id="grid" width="50" height="50" patternUnits="userSpaceOnUse">
          <path d="M 50 0 L 0 0 0 50" fill="none" stroke="rgba(255, 255, 255, 0.07)" strokeWidth="1" />
        </pattern>
        <marker id="rayArrow" viewBox="0 0 12 12" refX="10" refY="6" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 1 1 L 11 6 L 1 11 Z" fill="#ff1f3d" />
        </marker>
        <filter id="vehicleShadow" x="-50%" y="-50%" width="200%" height="200%">
          <feDropShadow dx="0" dy="4" stdDeviation="4" floodColor="#000000" floodOpacity="0.62" />
          <feDropShadow dx="0" dy="0" stdDeviation="5" floodColor="#ff1f3d" floodOpacity="0.3" />
        </filter>
      </defs>
      <rect width="1000" height="680" rx="8" fill="#07080a" />
      <rect width="1000" height="680" rx="8" fill="url(#grid)" />
      {points ? <polyline points={points} fill="none" stroke="#3a3d43" opacity="0.82" strokeLinecap="round" strokeLinejoin="round" strokeWidth="12" /> : null}
      {points ? <polyline points={points} fill="none" stroke="#d9d9d9" opacity="0.92" strokeLinecap="round" strokeLinejoin="round" strokeWidth="4" /> : null}
      {drivenPoints ? <polyline points={drivenPoints} fill="none" stroke="#ff1f3d" strokeLinecap="round" strokeLinejoin="round" strokeWidth="5" /> : null}
      {current && rayPolyline ? (
        <g>
          <polyline
            points={`${current[0]},${current[1]} ${rayPolyline}`}
            fill="none"
            stroke="#ff4d64"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="2"
            opacity="0.86"
            markerEnd="url(#rayArrow)"
          />
          {rayPoints.map((point, index) => {
            const [x, y] = projectPoint(point, bounds).split(",").map(Number);
            return <circle key={`${point.sequence}-${index}`} cx={x} cy={y} r="2.2" fill="#ff4d64" opacity={0.72 - index * 0.006} />;
          })}
        </g>
      ) : null}
      {current ? (
        <VehicleMarker x={current[0]} y={current[1]} orientation={orientation ?? 0} iconUrl={vehicleIconUrl} />
      ) : (
        <text x="500" y="340" textAnchor="middle" className="emptyMap">
          Waiting for GPS telemetry
        </text>
      )}
    </svg>
  );
}

function VehicleMarker({ x, y, orientation, iconUrl }: { x: number; y: number; orientation: number; iconUrl: string }) {
  const normalizedIconUrl = iconUrl.trim();
  if (normalizedIconUrl) {
    return (
      <g transform={`translate(${x} ${y}) rotate(${orientation})`} filter="url(#vehicleShadow)">
        <image href={normalizedIconUrl} x="-24" y="-34" width="48" height="68" preserveAspectRatio="xMidYMid meet" />
      </g>
    );
  }

  return (
    <g transform={`translate(${x} ${y}) rotate(${orientation})`} filter="url(#vehicleShadow)">
      <path d="M 0 -30 L 20 24 L 0 14 L -20 24 Z" fill="#f8f8f8" stroke="#09090b" strokeWidth="3" strokeLinejoin="round" />
      <path d="M 0 -18 L 8 13 L 0 9 L -8 13 Z" fill="#15161a" opacity="0.94" />
      <circle cx="0" cy="0" r="5" fill="#ff1f3d" stroke="#09090b" strokeWidth="2" />
    </g>
  );
}

function Metric({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <Card variant="outlined" sx={{ height: "100%", bgcolor: "rgba(5, 5, 6, 0.78)", boxShadow: "none" }}>
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
  return value.trim().replace(/\/$/, "");
}

function toWebSocketUrl(origin: string, path: string) {
  const url = new URL(path, origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

function buildTrack(samples: Array<TelemetryPacket | TraceSample>, fixedOrigin?: TrackPoint | null): TrackPoint[] {
  const gps = samples.filter(hasGps);
  if (gps.length === 0) {
    return [];
  }
  const origin = fixedOrigin ?? gps[0];
  return gps.map((packet) => {
    const projected = metersFromOrigin(origin.latitude, origin.longitude, packet.latitude, packet.longitude);
    return {
      sequence: packet.sequence,
      timestamp: packet.timestamp,
      latitude: packet.latitude,
      longitude: packet.longitude,
      heading: packet.heading,
      ...projected
    };
  });
}

function projectPacketFromOrigin(packet: TelemetryPacket | null, origin: TrackPoint | null): TrackPoint | null {
  if (!packet || !origin || packet.latitude === null || packet.longitude === null) {
    return null;
  }
  const projected = metersFromOrigin(origin.latitude, origin.longitude, packet.latitude, packet.longitude);
  return {
    sequence: packet.sequence,
    timestamp: packet.timestamp,
    latitude: packet.latitude,
    longitude: packet.longitude,
    heading: packet.heading,
    ...projected
  };
}

function buildRayPoints(currentPoint: TrackPoint | null, orientation: number | null, requestedCount: number): TrackPoint[] {
  if (!currentPoint || orientation === null || !Number.isFinite(requestedCount)) {
    return [];
  }
  const count = Math.max(0, Math.min(60, Math.round(requestedCount)));
  const radians = toRadians(orientation);
  const eastStep = Math.sin(radians) * RAY_SPACING_METERS;
  const northStep = Math.cos(radians) * RAY_SPACING_METERS;

  return Array.from({ length: count }, (_, index) => {
    const distanceMultiplier = index + 1;
    return {
      sequence: currentPoint.sequence + distanceMultiplier,
      timestamp: currentPoint.timestamp,
      latitude: currentPoint.latitude,
      longitude: currentPoint.longitude,
      heading: currentPoint.heading,
      xMeters: currentPoint.xMeters + eastStep * distanceMultiplier,
      yMeters: currentPoint.yMeters + northStep * distanceMultiplier
    };
  });
}

function hasGps(packet: TelemetryPacket | TraceSample): packet is TraceSample {
  return packet.latitude !== null && packet.longitude !== null;
}

function metersFromOrigin(originLat: number, originLon: number, lat: number, lon: number) {
  const metersPerDegreeLat = 111_320;
  const metersPerDegreeLon = metersPerDegreeLat * Math.cos(toRadians(originLat));
  return {
    xMeters: (lon - originLon) * metersPerDegreeLon,
    yMeters: (lat - originLat) * metersPerDegreeLat
  };
}

function computeOrientation(history: TelemetryPacket[]) {
  const latest = history[history.length - 1];
  if (!latest) {
    return null;
  }
  const gps = history.filter((packet) => packet.latitude !== null && packet.longitude !== null);
  const movementBearing = bearingFromRecentMovement(gps);
  if (movementBearing !== null) {
    return movementBearing;
  }
  if (latest.heading !== null) {
    return normalizeAngle(latest.heading);
  }
  return null;
}

function bearingFromRecentMovement(gps: TelemetryPacket[]) {
  if (gps.length < 2) {
    return null;
  }
  const current = gps[gps.length - 1];
  for (let index = gps.length - 2; index >= 0; index -= 1) {
    const previous = gps[index];
    const delta = metersFromOrigin(previous.latitude!, previous.longitude!, current.latitude!, current.longitude!);
    const distance = Math.hypot(delta.xMeters, delta.yMeters);
    if (distance >= 1.5) {
      return bearing(previous.latitude!, previous.longitude!, current.latitude!, current.longitude!);
    }
  }
  return null;
}

function bearing(lat1: number, lon1: number, lat2: number, lon2: number) {
  const phi1 = toRadians(lat1);
  const phi2 = toRadians(lat2);
  const delta = toRadians(lon2 - lon1);
  const y = Math.sin(delta) * Math.cos(phi2);
  const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(delta);
  return normalizeAngle(toDegrees(Math.atan2(y, x)));
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

function toDegrees(value: number) {
  return (value * 180) / Math.PI;
}
