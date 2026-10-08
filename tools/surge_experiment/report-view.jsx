// Копіюється в src/content/report/ReportContent.jsx штатного Data app.
import React, { useState } from "react";
import { DataComponent, DataTable, ReportSection, RichNarrative, useDataApp } from "../../data-app-public.jsx";

const statusText = { evaluated: "Оцінено", not_applicable: "Не застосовується", data_not_available: "Немає даних",
  insufficient_training_classes: "Бракує класів для навчання", no_selection_trial: "Немає оцінюваного trial" };
const value = (v) => v == null ? "—" : String(v);
const percent = (v) => v == null ? "—" : `${(v * 100).toFixed(2)}%`;
const columns = [
  { field: "queue_id", label: "ID черги" }, { field: "candidate_id", label: "Кандидат" },
  { field: "status", label: "Стан", renderCell: (v) => statusText[v] || v },
  { field: "observed_events", label: "Події", renderCell: value },
  { field: "tp_alerts", label: "TP", renderCell: value }, { field: "fp_alerts", label: "FP", renderCell: value },
  { field: "fn_events", label: "FN", renderCell: value },
  { field: "precision", label: "Precision", renderCell: percent },
  { field: "overall_recall", label: "Recall", renderCell: percent },
];

export function ReportContent() {
  const { snapshot, reviewedRows, visible, appTitle, canEdit, mode, setAppTitle } = useDataApp();
  const [candidate, setCandidate] = useState("all");
  const [selected, setSelected] = useState(null);
  const rows = reviewedRows("queue_results");
  const filtered = rows.filter((r) => candidate === "all" || r.candidate_id === candidate)
    .map((r) => ({...r, row_key: `${r.candidate_id}:${r.queue_id}`}));
  const dataIds = new Set(rows.filter((r) => r.status === "evaluated").map((r) => r.queue_id));
  const allIds = new Set(rows.map((r) => r.queue_id));
  const synthetic = snapshot.status === "fixture";
  const summary = synthetic
    ? "## Синтетична перевірка інтерфейсу\n\nЦе результат контрольного прикладу evaluator: одна подія та три окремі початкові попередження. Таблиця перевіряє TP, FP і відсутні значення. Вона не показує якість реального прогнозу."
    : `## Що можна сказати за цим запуском\n\nРезультати охоплюють ${dataIds.size} із ${allIds.size} черг. Це локальне порівняння на історії; воно не підтверджує точність 99% і не змінює робочі сповіщення. Висновок для кожної черги та причини виключень доступні після вибору рядка.`;
  return <article className="report-content surge-report" aria-label="Оцінка прогнозу AvelRen">
    <header className="report-hero">
      <h1 data-data-app-title contentEditable={canEdit && mode === "edit"} suppressContentEditableWarning
        onBlur={canEdit && mode === "edit" ? (e) => setAppTitle(e.currentTarget.textContent.trim() || appTitle) : undefined}>{appTitle}</h1>
    </header>
    {visible("surge-summary") && <ReportSection id="surge-summary" title="Підсумок перевірки" queryId="queue_results" sourceRows={rows} showHeading={false}>
      <RichNarrative id="surge-summary:body" value={summary} />
    </ReportSection>}
    {visible("surge-results") && <DataComponent id="surge-results" title="Результати кожної черги" kind="table"
      queryId="queue_results" sourceRows={filtered} displayRows={filtered}>
      <DataTable rows={filtered} columns={columns} label="Результати прогнозу по ID черг" compactNumbers={false}
        rowKey="row_key" selectedRowKey={selected?.row_key} onRowSelect={setSelected}
        rowActionLabel={(r) => `Пояснення для ${r.candidate_id}, черга ${r.queue_id}`}
        toolbarControls={<label>Кандидат <select aria-label="Кандидат" value={candidate} onChange={(e) => {setCandidate(e.target.value);setSelected(null);}}>
          <option value="all">Усі</option>{[...new Set(rows.map((r) => r.candidate_id))].map((id) => <option key={id} value={id}>{id}</option>)}
        </select></label>} />
    </DataComponent>}
    {selected && visible("surge-detail") && <ReportSection id="surge-detail" title="Знаменники та причини" queryId="queue_results" sourceRows={[selected]} showHeading={false}>
      <RichNarrative id="surge-detail:heading" value={`## ${selected.candidate_id} · черга ${selected.queue_id}`} />
      <dl data-reviewed-rows className="surge-detail-grid">
        <dt>Стан</dt><dd>{statusText[selected.status] || selected.status}</dd>
        <dt>Висновок</dt><dd>{value(selected.stop_status)}</dd>
        <dt>Невідоме майбутнє попереджень</dt><dd>{value(selected.unassessable_alerts)}</dd>
        <dt>Події без достатньої історії</dt><dd>{value(selected.events_without_history)}</dd>
        <dt>Причина невизначеного precision / recall</dt><dd>{selected.precision_reason || "—"} / {selected.recall_reason || "—"}</dd>
        <dt>Попередження TP / знаменник</dt><dd>{selected.tp_alerts == null ? "—" : `${selected.tp_alerts} / ${selected.tp_alerts + selected.fp_alerts}`}</dd>
        <dt>Зіставлені події / знаменник</dt><dd>{selected.matched_events == null ? "—" : `${selected.matched_events} / ${selected.observed_events}`}</dd>
        <dt>Область попереджень</dt><dd>{selected.cohorts ? `${selected.cohorts.alert_start} → ${selected.cohorts.alert_end}` : "—"}</dd>
        <dt>Область подій</dt><dd>{selected.cohorts ? `${selected.cohorts.event_start} → ${selected.cohorts.event_end}` : "—"}</dd>
        <dt>Виключені події</dt><dd>{JSON.stringify(selected.excluded_events || {})}</dd>
        <dt>Довірчий інтервал precision / recall</dt><dd>{selected.precision_ci?.reason || "—"} / {selected.recall_ci?.reason || "—"}</dd>
      </dl>
    </ReportSection>}
    {visible("surge-methods") && <ReportSection id="surge-methods" title="Як читати результат" queryId="queue_results" sourceRows={rows} showHeading={false}>
      <RichNarrative id="surge-methods:body" value={"## Як читати результат\n\n**TP** — початкове попередження, зіставлене з однією чистою подією. **FP** — нездійснене попередження з повністю відомим майбутнім. **FN** — відома подія без завчасного попередження. Нагадування не є новими прогнозами.\n\nPrecision оцінює частку справджених попереджень, recall — частку помічених подій. Їхні часові області різні, тому знаменники показано окремо. «—» означає відсутню оцінку, а не нуль.\n\nFrozen застосовується лише до ID 1, 6, 17, 29; Chop-local — лише до 17. Інші рядки мають явне «Не застосовується». Тижневий зріз не дає 28 діб для блочного довірчого інтервалу. Подія — чистий приріст черги, не кількість нових реєстрацій."} />
    </ReportSection>}
  </article>;
}
