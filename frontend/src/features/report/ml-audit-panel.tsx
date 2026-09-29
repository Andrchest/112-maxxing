import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { apiFetch } from '@/shared/lib/api';
import { useAuthStore } from '@/entities/session';

interface AuditResult {
  run_id: string | null;
  generated_at: string | null;
  evidence_method: 'binary_token' | 'attention_weights';
  earned_weight: number;
  total_weight: number;
  model: string;
  rubric_version: string;
  score_percent: number | null;
  coverage_percent: number;
  categories: { category: string; score_percent: number | null }[];
  results: {
    criterion: { id: string; category: string; question: string; weight: number };
    passed: boolean | null;
    decision_token: 'да' | 'нет' | null;
    awarded_weight: number | null;
    issue: string | null;
    evidence: { source_id: string; start: number; end: number; quote: string }[];
  }[];
  sources: { id: string; text: string; kind: 'dialogue' | 'card' }[];
}

const ISSUES: Record<string, string> = {
  no_source: 'Нет доступного текста для проверки.',
  context_too_large: 'Текст превышает контекст модели; он не был обрезан.',
  inference_error: 'Технический сбой: модель не выдала ровно один токен «да» или «нет».',
  provider_not_configured: 'Настройте локальную модель SIM_EXPLANATION_LLM_PROVIDER=llama_cpp или attention-адаптер.',
  attention_unavailable: 'Attention-модель недоступна, несовместима или не уложилась в лимит.',
};

export function MLAuditPanel({ sessionId }: { sessionId: string }) {
  const queryClient = useQueryClient();
  const viewer = useAuthStore((state) => state.user);
  const queryKey = ['ml-audit', sessionId, viewer?.id, viewer?.user_role];
  const saved = useQuery({
    queryKey,
    queryFn: () => apiFetch<AuditResult | null>(`/reports/${encodeURIComponent(sessionId)}/ml-audit`),
    retry: false,
    refetchInterval: (query) => query.state.data?.score_percent == null ? 10000 : false,
  });
  const result = saved.data;
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);

  async function evaluate() {
    setPending(true);
    setError(false);
    await queryClient.cancelQueries({ queryKey });
    try {
      const audit = await apiFetch<AuditResult>(`/reports/${encodeURIComponent(sessionId)}/ml-audit?regenerate=true`, { method: 'POST' });
      queryClient.setQueryData(queryKey, audit);
    } catch {
      setError(true);
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader><h2 className="font-heading text-base font-medium">ML-аудит карточки и диалога</h2></CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-xs text-muted-foreground">
          Учебная рекомендация, не официальный балл и не юридическое заключение.
          Результаты сохраняются в истории аудита. Автоматическая проверка запускается после завершения вызова.
          Повторная проверка создаёт новую запись, не меняя официальный балл.
        </p>
        <Button disabled={pending} onClick={() => void evaluate()}>
          {pending ? 'Проверяем…' : 'Оценить с помощью ML'}
        </Button>
        {error && <p role="alert">Не удалось выполнить ML-аудит. Основной отчёт не изменён.</p>}
        {saved.isError && !result && <p role="alert">Не удалось загрузить сохранённый аудит.</p>}
        {result && <div aria-live="polite" className="space-y-3">
          <p>ML-балл: {result.score_percent === null ? 'технически недоступен' : `${result.score_percent}%`}
            {' · '}Проверено: {result.coverage_percent}% веса критериев</p>
          <p>Сумма весов выполненных критериев: {result.earned_weight} / {result.total_weight}</p>
          <p className="text-xs text-muted-foreground">Модель: {result.model} · Регламент: {result.rubric_version}</p>
          <p className="text-xs text-muted-foreground">
            Метод: {result.evidence_method === 'attention_weights' ? 'принудительный да/нет + attention-веса' : 'принудительный да/нет; HTTP-режим без attention и цитат'}.
            {' '}Сохранено: {result.generated_at ?? '—'}
          </p>
          <ul>{result.categories.map((category) => <li key={category.category}>
            {category.category}: {category.score_percent === null ? 'не определён' : `${category.score_percent}%`}
          </li>)}</ul>
          {result.results.map((item) => <section key={item.criterion.id} className="rounded border p-3 space-y-2">
            <h3 className="font-medium">{item.criterion.category}</h3>
            <p>{item.criterion.question}</p>
            <p>Вес: {item.criterion.weight} · Токен: {item.decision_token ?? 'Технический сбой'} · Вклад: {item.awarded_weight ?? '—'}</p>
            {item.issue && <p className="text-xs text-muted-foreground">{ISSUES[item.issue] ?? 'Оценка недоступна.'}</p>}
            {item.passed === false && item.evidence.length === 0 && <p className="text-xs">Подтверждение действия не найдено; цитаты отсутствия не существует.</p>}
            {item.evidence.map((evidence, index) => {
              const source = result.sources.find((s) => s.id === evidence.source_id);
              if (!source) return null;
              // Backend offsets count Unicode code points, not JS UTF-16 code units.
              const chars = Array.from(source.text);
              return <blockquote key={`${evidence.source_id}:${index}`} className="border-l-2 pl-3 whitespace-pre-wrap">
                <p className="text-xs text-muted-foreground">{source.kind === 'card' ? 'Поле карточки' : 'Реплика оператора'}: {source.id}</p>
                {chars.slice(0, evidence.start).join('')}
                <mark>{chars.slice(evidence.start, evidence.end).join('')}</mark>
                {chars.slice(evidence.end).join('')}
              </blockquote>;
            })}
          </section>)}
        </div>}
      </CardContent>
    </Card>
  );
}
