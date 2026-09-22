import { useState } from "react";
import QuestionReferenceImages from "./QuestionReferenceImages";
export type ItemQuestion = { id: string; name: string; room: string; quantity: number; question: string; photo: boolean; answers: { id: string; label: string; action: string; notice: string; acknowledge: boolean }[]; saved?: { answer_id: string; acknowledged: boolean } };
type Props = { questions: ItemQuestion[]; endpoint: string; linkKey: string; session: string; onSave: (answer: { question_id: string; answer_id: string; acknowledged: boolean }) => Promise<void> };
export default function CustomerItemQuestions(props: Props) {
 return <div className="cm-checklist">{props.questions.map(question => <Question key={question.id} question={question} {...props} />)}</div>;
}
function Question({ question, endpoint, linkKey, session, onSave }: Props & { question: ItemQuestion }) {
 const [choice, setChoice] = useState(question.saved?.answer_id || "");
 const [ack, setAck] = useState(question.saved?.acknowledged || false);
 const [busy, setBusy] = useState(false), [error, setError] = useState("");
 const option = question.answers.find(a => a.id === choice);
 const saved = question.saved?.answer_id === choice && question.saved?.acknowledged === ack;
 async function save() { setBusy(true); setError(""); try { await onSave({ question_id: question.id, answer_id: choice, acknowledged: ack }); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }
 return <fieldset disabled={busy} style={{ border: "1px solid #e4d9d5", borderRadius: 10, padding: 16, margin: "0 0 16px", minWidth: 0 }}>
  <legend><strong>{question.name}</strong>{question.room ? ` · ${question.room}` : ""} · Qty {question.quantity}</legend>
  {question.photo && <QuestionReferenceImages name={question.name} room={question.room} endpoint={`${endpoint}/question-images`} linkKey={linkKey} session={session} />}
  <p><strong>{question.question}</strong></p>
  <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>{question.answers.map(answer => <label className="cm-check-item" key={answer.id}><input type="radio" name={question.id} checked={choice === answer.id} onChange={() => { setChoice(answer.id); setAck(false); }} />{answer.label}</label>)}</div>
  {option?.notice && <p role="status">{option.notice}</p>}
  {option?.acknowledge && <label className="cm-check-item"><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} />I understand these instructions.</label>}
  {error && <p role="alert">{error}</p>}
  <button type="button" className="slds-button cm-primary" disabled={!option || (option.acknowledge && !ack) || saved} onClick={() => void save()}>{busy ? "Saving..." : saved ? "Saved" : "Save answer"}</button>
  {saved && option && <p role="status">{({ exclude: "Excluded from shipment and estimated volume.", prepare: "Preparation required before moving.", review: "Flagged for the moving team to review.", notice: "Instructions acknowledged.", none: "Item remains included." } as Record<string, string>)[option.action]}</p>}
 </fieldset>;
}
