// The phone widget's mic level meter (SPEC §32 "level meter"; D9, D12 DESIGN: "the level meter
// reads the local mic" — never the caller's audio, and never a value the backend sent). A plain
// AnalyserNode RMS reading over the LOCAL microphone track, polled on an interval. The
// `AudioContext` is built through an injected factory so tests run against a fake — jsdom ships
// no Web Audio API at all.

export interface AnalyserLike {
  fftSize: number;
  readonly frequencyBinCount: number;
  getByteTimeDomainData(array: Uint8Array): void;
}

export interface MediaStreamAudioSourceLike {
  connect(destination: AnalyserLike): void;
  disconnect(): void;
}

export interface AudioContextLike {
  createAnalyser(): AnalyserLike;
  createMediaStreamSource(stream: MediaStream): MediaStreamAudioSourceLike;
  close(): Promise<void> | void;
}

export interface LevelMeterHandle {
  stop(): void;
}

export interface LevelMeterOptions {
  audioContextFactory?: () => AudioContextLike;
  /** Wraps the raw local `MediaStreamTrack` for `AudioContextLike.createMediaStreamSource`.
   * Defaults to `new MediaStream([track])` — injectable because jsdom has no `MediaStream`
   * constructor either. */
  mediaStreamFactory?: (track: MediaStreamTrack) => MediaStream;
  intervalMs?: number;
}

const DEFAULT_INTERVAL_MS = 100;
const DEFAULT_FFT_SIZE = 512;

/** RMS of the analyser's current time-domain buffer, normalised to 0..1. Pure, so it is unit
 * tested directly against a scripted fake analyser instead of only through the polling loop. */
export function computeLevel(analyser: AnalyserLike): number {
  const data = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteTimeDomainData(data);
  if (data.length === 0) return 0;
  let sumSquares = 0;
  for (const byte of data) {
    const normalized = (byte - 128) / 128;
    sumSquares += normalized * normalized;
  }
  return Math.min(1, Math.sqrt(sumSquares / data.length));
}

function defaultAudioContextFactory(): AudioContextLike {
  return new AudioContext() as unknown as AudioContextLike;
}

function defaultMediaStreamFactory(track: MediaStreamTrack): MediaStream {
  return new MediaStream([track]);
}

/** Starts polling `track`'s level at `intervalMs`, calling `onLevel` with each 0..1 reading,
 * until {@link LevelMeterHandle.stop} is called. */
export function startLevelMeter(
  track: MediaStreamTrack,
  onLevel: (level: number) => void,
  options: LevelMeterOptions = {},
): LevelMeterHandle {
  const audioContext = (options.audioContextFactory ?? defaultAudioContextFactory)();
  const mediaStreamFactory = options.mediaStreamFactory ?? defaultMediaStreamFactory;
  const analyser = audioContext.createAnalyser();
  analyser.fftSize = DEFAULT_FFT_SIZE;
  const source = audioContext.createMediaStreamSource(mediaStreamFactory(track));
  source.connect(analyser);

  const intervalId = setInterval(() => {
    onLevel(computeLevel(analyser));
  }, options.intervalMs ?? DEFAULT_INTERVAL_MS);

  return {
    stop(): void {
      clearInterval(intervalId);
      source.disconnect();
      void audioContext.close();
    },
  };
}
