import { useEffect, useId, useRef, useState } from "react";
import QuestionReferenceImages from "./QuestionReferenceImages";
export type ItemQuestion = { id: string; rule_id?: string; all_items?: boolean; items?: { id: string; label: string; room: string }[]; name: string; label?: string; room: string; quantity: number; question: string; photo: boolean; answers: { id: string; label: string; action: string; notice: string; acknowledge: boolean }[]; saved?: { answer_id: string; acknowledged: boolean; pending?: boolean; selected_items?: string[] } };
type Props = { active?: boolean; visibleIds?: Set<string>; validationAttempt?: number; disabled?: boolean; questions: ItemQuestion[]; endpoint: string; linkKey: string; session: string; onSave: (answer: { question_id: string; answer_id: string; acknowledged: boolean; pending: boolean; selected_items?: string[] }) => Promise<void> };
export default function CustomerItemQuestions(props: Props) {
 const list = useRef<HTMLDivElement>(null);
 useEffect(() => {
  if (!props.validationAttempt) return;
  const invalid = list.current?.querySelector<HTMLElement>(':scope > div:not([hidden]) [aria-invalid="true"]');
  invalid?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  (invalid?.matches('input') ? invalid : invalid?.querySelector<HTMLElement>('input'))?.focus({ preventScroll: true });
 }, [props.validationAttempt]);
 return <div ref={list} className="cm-checklist">{props.questions.map(question => <div key={question.id} hidden={props.visibleIds ? !props.visibleIds.has(question.id) : false}><Question question={question} {...props} active={!props.visibleIds || props.visibleIds.has(question.id)} /></div>)}</div>;
}
function Question({ question, endpoint, linkKey, session, onSave, disabled, validationAttempt = 0, active = true }: Props & { question: ItemQuestion }) {
 const [choice, setChoice] = useState(question.saved?.answer_id || "");
 const [selectedItems, setSelectedItems] = useState<string[]>(question.saved?.selected_items || []);
 const [ack, setAck] = useState(question.saved?.acknowledged || false);
 const [busy, setBusy] = useState(false), [error, setError] = useState("");
 const saveVersion = useRef(0);
 const errorId = useId();
 const option = question.answers.find(a => a.id === choice);
 const missingChoice = validationAttempt > 0 && !choice;
 const missingAck = !!option?.acknowledge && !ack;
 const needsItems = !!question.all_items && !!option && option.action !== 'none';
 const missingItems = needsItems && selectedItems.length === 0;
 const saved = question.saved?.answer_id === choice && question.saved?.acknowledged === ack && (!question.all_items || JSON.stringify(question.saved?.selected_items || []) === JSON.stringify(selectedItems));
 async function save(answerId: string, acknowledged: boolean, items = selectedItems) {
   const version = ++saveVersion.current;
   const answer = question.answers.find(a => a.id === answerId);
   if (!answer) return;
   setBusy(true); setError("");
   try { await onSave({ question_id: question.id, answer_id: answerId, acknowledged, pending: (answer.acknowledge && !acknowledged) || (!!question.all_items && answer.action !== 'none' && !items.length), selected_items: question.all_items ? items : undefined }); }
   catch (e) { if (version === saveVersion.current) setError((e as Error).message); }
   finally { if (version === saveVersion.current) setBusy(false); }
 }
 return <fieldset disabled={disabled} className={`cm-item-question${missingChoice || missingAck || (validationAttempt > 0 && missingItems) ? ' cm-item-question-invalid' : ''}`}>
  <legend><strong>{question.label || question.name}</strong>{question.room && <span>{question.room}</span>}{!question.all_items && <span>Qty {question.quantity}</span>}</legend>
  {question.photo && <QuestionReferenceImages active={active} name={question.name} room={question.room} endpoint={`${endpoint}/question-images`} linkKey={linkKey} session={session} />}
  <p><strong>{question.question}</strong></p>
  <div className="cm-item-answers" role="group" aria-invalid={missingChoice || undefined} aria-describedby={missingChoice ? errorId : undefined}>{question.answers.map(answer => <label className="cm-check-item" key={answer.id}><input type="radio" name={question.id} checked={choice === answer.id} onChange={() => { setChoice(answer.id); setAck(false); setSelectedItems([]); void save(answer.id, false, []); }} />{answer.label}</label>)}</div>
  {missingChoice && <small id={errorId} className="cm-field-error" role="alert">Choose an answer to continue.</small>}
  {needsItems && <div className="cm-applicable-items" role="group" aria-label="Select applicable items" aria-invalid={validationAttempt > 0 && missingItems || undefined}>
    <p><strong>Select the items this applies to</strong></p>
    {(question.items || []).map(item => <label className="cm-check-item" key={item.id}><input type="checkbox" checked={selectedItems.includes(item.id)} onChange={e => {
      const next = e.target.checked ? [...selectedItems, item.id] : selectedItems.filter(id => id !== item.id);
      setSelectedItems(next); setAck(false); void save(choice, false, next);
    }} />{item.label}{item.room ? ` - ${item.room}` : ''}</label>)}
    {!question.items?.length && <p>Add the applicable items to your inventory and generate an updated report.</p>}
    {validationAttempt > 0 && missingItems && <small className="cm-field-error" role="alert">Select at least one item.</small>}
  </div>}
  {option?.notice && <p role="status">{option.notice}</p>}
  {option?.acknowledge && <label className={`cm-check-item${missingAck ? ' cm-ack-invalid' : ''}`}><input type="checkbox" aria-invalid={missingAck || undefined} aria-describedby={missingAck ? errorId : undefined} checked={ack} onChange={e => { setAck(e.target.checked); void save(choice, e.target.checked); }} />I understand these instructions.</label>}
  {error && <p role="alert">Could not save: {error} <button type="button" className="slds-button" onClick={() => void save(choice, ack)}>Try again</button></p>}
  {missingAck && <small id={errorId} className="cm-field-error" role="alert">Please acknowledge the instructions to complete this answer.</small>}
  {saved && !error && !busy && option && (!option.acknowledge || ack) && !missingItems && option.action !== "none" && <p role="status">{({ exclude: "Excluded from shipment and estimated volume.", prepare: "Preparation required before moving.", review: "Flagged for the moving team to review.", notice: "Instructions acknowledged." } as Record<string, string>)[option.action]}</p>}
 </fieldset>;
}
