import type { ItemQuestion } from './CustomerItemQuestions';

export function groupTerms(questions: ItemQuestion[] = []) {
  const groups = new Map<string, ItemQuestion[]>();
  for (const question of questions) {
    const key = question.rule_id || question.question;
    groups.set(key, [...(groups.get(key) || []), question]);
  }
  return [...groups.values()];
}

export function needsTermAnswer(question: ItemQuestion) {
  const answer = question.answers.find(row => row.id === question.saved?.answer_id);
  return !answer || !!question.saved?.pending || (answer.acknowledge && !question.saved?.acknowledged);
}

export function requiredQuestionTarget(missing: string[], groups: ItemQuestion[][]) {
  const termsIndex = groups.findIndex(group => group.some(needsTermAnswer));
  return { step: missing[0] || 'items', termsIndex: Math.max(0, termsIndex) };
}
