import { useRef, useState } from "react";
import QuestionReferenceImages from "./QuestionReferenceImages";
export type ItemQuestion = { id: string; name: string; label?: string; room: string; quantity: number; question: string; photo: boolean; answers: { id: string; label: string; action: string; notice: string; acknowledge: boolean }[]; saved?: { answer_id: string; acknowledged: boolean; pending?: boolean } };
type Props = { disabled?: boolean; questions: ItemQuestion[]; endpoint: string; linkKey: string; session: string; onSave: (answer: { question_id: string; answer_id: string; acknowledged: boolean; pending: boolean }) => Promise<void> };
export default function CustomerItemQuestions(props: Props) {
 return <div className="cm-checklist">{props.questions.map(question => <Question key={question.id} question={question} {...props} />)}</div>;
}
function Question({ question, endpoint, linkKey, session, onSave, disabled }: Props & { question: ItemQuestion }) {
 const [choice, setChoice] = useState(question.saved?.answer_id || "");
 const [ack, setAck] = useState(question.saved?.acknowledged || false);
 const [busy, setBusy] = useState(false), [error, setError] = useState("");
 const saveVersion = useRef(0);
 const option = question.answers.find(a => a.id === choice);
 const saved = question.saved?.answer_id === choice && question.saved?.acknowledged === ack;
 async function save(answerId: string, acknowledged: boolean) {
   const version = ++saveVersion.current;
   const answer = question.answers.find(a => a.id === answerId);
   if (!answer) return;
   setBusy(true); setError("");
   try { await onSave({ question_id: question.id, answer_id: answerId, acknowledged, pending: answer.acknowledge && !acknowledged }); }
   catch (e) { if (version === saveVersion.current) setError((e as Error).message); }
   finally { if (version === saveVersion.current) setBusy(false); }
 }
 return <fieldset disabled={disabled} className="cm-item-question">
  <legend><strong>{question.label || question.name}</strong>{question.room && <span>{question.room}</span>}<span>Qty {question.quantity}</span></legend>
  {question.photo && <QuestionReferenceImages name={question.name} room={question.room} endpoint={`${endpoint}/question-images`} linkKey={linkKey} session={session} />}
  <p><strong>{question.question}</strong></p>
  <div className="cm-item-answers">{question.answers.map(answer => <label className="cm-check-item" key={answer.id}><input type="radio" name={question.id} checked={choice === answer.id} onChange={() => { setChoice(answer.id); setAck(false); void save(answer.id, false); }} />{answer.label}</label>)}</div>
  {option?.notice && <p role="status">{option.notice}</p>}
  {option?.acknowledge && <label className="cm-check-item"><input type="checkbox" checked={ack} onChange={e => { setAck(e.target.checked); void save(choice, e.target.checked); }} />I understand these instructions.</label>}
  {error && <p role="alert">Could not save: {error} <button type="button" className="slds-button" onClick={() => void save(choice, ack)}>Try again</button></p>}
  {option?.acknowledge && !ack && <small>Please acknowledge the instructions to complete this answer.</small>}
  {saved && !error && !busy && option && (!option.acknowledge || ack) && option.action !== "none" && <p role="status">{({ exclude: "Excluded from shipment and estimated volume.", prepare: "Preparation required before moving.", review: "Flagged for the moving team to review.", notice: "Instructions acknowledged." } as Record<string, string>)[option.action]}</p>}
 </fieldset>;
}
