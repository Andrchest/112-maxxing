// §29 items 5-7: transcript, audio playback, and click-transcript-to-seek. Fetches each audio
// segment as an authenticated blob the first time it is needed (an `<audio>` element cannot carry
// a Bearer header, D9/D12) and keeps one object URL per fetched segment for the life of this
// component, revoking every one of them on unmount.
//
// Calls (I3 E6c backend, rendered since E6d): a segment of a call carries `call_id` and the call's
// party label `call_party_ru`. When the transcript has any, its turns are grouped per call, in the
// order the calls first speak, each group headed by its party label («Вызов 112: абонент»,
// «Звонок ДДС: Оператор 112»); on a ДДС call «Оператор» is the ДДС trainee. A transcript without
// them renders as one list, exactly as before.
// I5 E40 (Q-E16-3 variant b, ТЗ ¶383): a «Скачать MP3» link next to the audio controls,
// downloading the segment currently loaded into the player (activeAudioSegmentId) as MP3.
import { useEffect, useRef, useState } from 'react';
import { Badge } from '@/shared/ui/badge';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { getAudioSegment, getAudioSegmentMp3, problemMessageRu, type AudioSegmentRef, type ProblemCode, type TranscriptSegmentView } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { saveBlob } from '@/shared/lib/download';
import { isTranscriptSegmentPlaying, seekTargetForTranscriptSegment } from '@/shared/media/report-audio';
import { groupTranscriptByCall } from './call-groups';

const SPEAKER_LABEL_KEY = {
  OPERATOR: 'speakerOperator',
  CALLER: 'speakerCaller',
} as const satisfies Record<TranscriptSegmentView['speaker'], keyof typeof ru>;

interface PendingSeek {
  audioSegmentId: string;
  offsetSeconds: number;
  /** Distinguishes two clicks on the same offset so the seek effect always re-fires. */
  token: number;
}

interface TranscriptAudioPanelProps {
  sessionId: string;
  transcript: readonly TranscriptSegmentView[];
  audioSegments: readonly AudioSegmentRef[];
}

export function TranscriptAudioPanel({ sessionId, transcript, audioSegments }: TranscriptAudioPanelProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const seekTokenRef = useRef(0);
  const objectUrlsRef = useRef<Record<string, string>>({});
  const [objectUrls, setObjectUrls] = useState<Record<string, string>>({});
  const [activeAudioSegmentId, setActiveAudioSegmentId] = useState<string | null>(null);
  const [loadingSegmentId, setLoadingSegmentId] = useState<string | null>(null);
  const [currentTimeSeconds, setCurrentTimeSeconds] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [seekRequest, setSeekRequest] = useState<PendingSeek | null>(null);
  const [downloadingMp3, setDownloadingMp3] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  useEffect(() => {
    objectUrlsRef.current = objectUrls;
  }, [objectUrls]);

  // Revoke every object URL this panel created, once, on unmount (D12 design decision #2).
  useEffect(() => {
    return () => {
      for (const url of Object.values(objectUrlsRef.current)) {
        URL.revokeObjectURL(url);
      }
    };
  }, []);

  useEffect(() => {
    if (!seekRequest) return;
    const url = objectUrls[seekRequest.audioSegmentId];
    const audioEl = audioRef.current;
    if (!url || !audioEl) return;
    audioEl.currentTime = seekRequest.offsetSeconds;
    try {
      const playResult = audioEl.play();
      if (playResult && typeof playResult.catch === 'function') {
        playResult.catch(() => {
          /* autoplay can be refused by the browser; the trainee can press play manually */
        });
      }
    } catch {
      /* the test environment (jsdom) has no real media playback */
    }
  }, [seekRequest, objectUrls]);

  async function handleTranscriptClick(segment: TranscriptSegmentView): Promise<void> {
    setErrorMessage(null);
    const target = seekTargetForTranscriptSegment(segment, audioSegments);
    if (!target) return;

    let url = objectUrls[target.audioSegmentId];
    if (!url) {
      setLoadingSegmentId(target.audioSegmentId);
      try {
        const blob = await getAudioSegment(sessionId, target.audioSegmentId);
        url = URL.createObjectURL(blob);
        setObjectUrls((previous) => ({ ...previous, [target.audioSegmentId]: url as string }));
      } catch (error) {
        setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('reportAudioLoadFailed'));
        setLoadingSegmentId(null);
        return;
      }
      setLoadingSegmentId(null);
    }

    setActiveAudioSegmentId(target.audioSegmentId);
    seekTokenRef.current += 1;
    setSeekRequest({ audioSegmentId: target.audioSegmentId, offsetSeconds: target.offsetSeconds, token: seekTokenRef.current });
  }

  const activeUrl = activeAudioSegmentId ? objectUrls[activeAudioSegmentId] : undefined;

  // I5 E40: downloads the segment currently loaded into the player, not the whole transcript — the
  // brief places «Скачать MP3» next to the recording controls, which is per-segment (D9's
  // `getAudioSegment` granularity), not a single per-session file.
  async function handleDownloadMp3(): Promise<void> {
    if (!activeAudioSegmentId) return;
    setDownloadError(null);
    setDownloadingMp3(true);
    try {
      const blob = await getAudioSegmentMp3(sessionId, activeAudioSegmentId);
      saveBlob(blob, `${sessionId}-${activeAudioSegmentId}.mp3`);
    } catch (error) {
      setDownloadError(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('reportAudioLoadFailed'));
    } finally {
      setDownloadingMp3(false);
    }
  }

  function renderSegment(segment: TranscriptSegmentView) {
    const target = seekTargetForTranscriptSegment(segment, audioSegments);
    const playing = isTranscriptSegmentPlaying(segment, activeAudioSegmentId, currentTimeSeconds, audioSegments);
    const audioSegment = segment.audio_segment_id ? audioSegments.find((s) => s.audio_segment_id === segment.audio_segment_id) : null;
    return (
      <li key={segment.id}>
        <button
          type="button"
          disabled={!target}
          onClick={() => void handleTranscriptClick(segment)}
          className={`flex w-full flex-col items-start gap-0.5 rounded-md px-1.5 py-1 text-left text-sm transition-colors ${
            playing ? 'bg-primary/10 ring-1 ring-primary' : target ? 'hover:bg-muted' : 'cursor-default opacity-70'
          }`}
        >
          <span className="flex items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline">{t(SPEAKER_LABEL_KEY[segment.speaker])}</Badge>
            {loadingSegmentId === segment.audio_segment_id ? '…' : null}
            {audioSegment?.purged ? t('problemAudioPurged') : null}
          </span>
          <span>{segment.text}</span>
        </button>
      </li>
    );
  }

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('reportTranscriptTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <audio
          ref={audioRef}
          src={activeUrl}
          controls
          className="w-full"
          onTimeUpdate={(event) => setCurrentTimeSeconds(event.currentTarget.currentTime)}
        />
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void handleDownloadMp3()}
            disabled={!activeAudioSegmentId || downloadingMp3}
          >
            {downloadingMp3 ? t('reportDownloadingMp3') : t('reportDownloadMp3')}
          </Button>
        </div>
        {errorMessage ? (
          <p role="alert" className="text-xs text-destructive">
            {errorMessage}
          </p>
        ) : null}
        {downloadError ? (
          <p role="alert" className="text-xs text-destructive">
            {downloadError}
          </p>
        ) : null}
        {transcript.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('reportTranscriptEmpty')}</p>
        ) : (
          <div className="flex max-h-96 flex-col gap-2 overflow-auto">
            {groupTranscriptByCall(transcript).map((group) => (
              <section key={group.callId ?? 'no-call'} className="flex flex-col gap-1" data-slot="transcript-call-group">
                {group.callId !== null ? (
                  <h3 className="text-xs font-medium text-muted-foreground" data-slot="transcript-call-heading">
                    {group.partyRu ?? t('reportCallPartyUnknown')}
                  </h3>
                ) : null}
                <ul className="flex flex-col gap-1">{group.segments.map(renderSegment)}</ul>
              </section>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
