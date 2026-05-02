import { create } from "zustand";

export type ReplayStatus = "idle" | "playing" | "paused" | "stopped" | "finished";

export type ReplayState = {
  status: ReplayStatus;
  current_index: number;
  total_samples: number;
  replay_speed: number;
  stream_interval: number | null;
  loop: boolean;
  vbo_file: string;
};

export type TelemetryPacket = {
  sequence: number;
  timestamp: number;
  latitude: number | null;
  longitude: number | null;
  speed: number | null;
  heading: number | null;
  altitude: number | null;
  satellites: number | null;
  throttle: number | null;
  brake: number | null;
  steering: number | null;
  gear: number | null;
  lap: number | null;
  raw: Record<string, unknown>;
};

type ConnectionState = "offline" | "connecting" | "live";

type TelemetryStore = {
  apiUrl: string;
  connection: ConnectionState;
  latest: TelemetryPacket | null;
  history: TelemetryPacket[];
  telemetryActive: boolean;
  frequencyHz: string;
  replaySpeed: string;
  rayPointCount: string;
  vehicleIconUrl: string;
  timingDirty: boolean;
  setApiUrl: (apiUrl: string) => void;
  setConnection: (connection: ConnectionState) => void;
  setTelemetryActive: (telemetryActive: boolean) => void;
  setFrequencyHz: (frequencyHz: string) => void;
  setReplaySpeed: (replaySpeed: string) => void;
  setRayPointCount: (rayPointCount: string) => void;
  setVehicleIconUrl: (vehicleIconUrl: string) => void;
  syncTiming: (streamInterval: number | null, replaySpeed: number) => void;
  acceptTiming: (streamInterval: number | null, replaySpeed: number) => void;
  resetTelemetry: () => void;
  pushPacket: (packet: TelemetryPacket) => void;
};

const MAX_POINTS = 1800;

export const useTelemetryStore = create<TelemetryStore>((set) => ({
  apiUrl: "",
  connection: "offline",
  latest: null,
  history: [],
  telemetryActive: false,
  frequencyHz: "10",
  replaySpeed: "1",
  rayPointCount: "12",
  vehicleIconUrl: "",
  timingDirty: false,
  setApiUrl: (apiUrl) => set({ apiUrl }),
  setConnection: (connection) => set({ connection }),
  setTelemetryActive: (telemetryActive) => set({ telemetryActive }),
  setFrequencyHz: (frequencyHz) => set({ frequencyHz, timingDirty: true }),
  setReplaySpeed: (replaySpeed) => set({ replaySpeed, timingDirty: true }),
  setRayPointCount: (rayPointCount) => set({ rayPointCount }),
  setVehicleIconUrl: (vehicleIconUrl) => set({ vehicleIconUrl }),
  syncTiming: (streamInterval, replaySpeed) =>
    set((state) =>
      state.timingDirty
        ? state
        : {
            frequencyHz: intervalToHz(streamInterval),
            replaySpeed: String(replaySpeed)
          }
    ),
  acceptTiming: (streamInterval, replaySpeed) =>
    set({
      frequencyHz: intervalToHz(streamInterval),
      replaySpeed: String(replaySpeed),
      timingDirty: false
    }),
  resetTelemetry: () => set({ latest: null, history: [] }),
  pushPacket: (packet) =>
    set((state) => {
      if (!state.telemetryActive) {
        return state;
      }
      if (state.history[state.history.length - 1]?.sequence === packet.sequence) {
        return { latest: packet };
      }
      return {
        latest: packet,
        history: [...state.history, packet].slice(-MAX_POINTS)
      };
    })
}));

function intervalToHz(seconds: number | null) {
  if (!seconds) {
    return "10";
  }
  return (1 / seconds).toFixed(2).replace(/\.?0+$/, "");
}
