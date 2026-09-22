"""Company-managed inventory questions and report-scoped answers."""
import hashlib
import json
import re
from typing import Literal
from pydantic import BaseModel, Field, model_validator
from models import InventoryCatalogItem


def normalized(text):
    return re.sub(r'[^a-z0-9]+', ' ', str(text or '').lower()).strip()


class AnswerOption(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=100)
    action: Literal['none', 'notice', 'exclude', 'prepare', 'review'] = 'none'
    notice: str = Field(default='', max_length=2000)
    acknowledge: bool = False


class QuestionRule(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=500)
    enabled: bool = True
    item_ids: list[str] = Field(default_factory=list, max_length=500)
    words: list[str] = Field(default_factory=list, max_length=50)
    photo: bool = True
    answers: list[AnswerOption] = Field(min_length=2, max_length=8)

    @model_validator(mode='after')
    def valid(self):
        if not self.title.strip() or not self.question.strip(): raise ValueError('Enter a title and question')
        if not self.item_ids and not any(normalized(word) for word in self.words): raise ValueError('Select items or enter matching words')
        if len({a.id for a in self.answers}) != len(self.answers): raise ValueError('Answer IDs must be unique')
        if any(not a.label.strip() or (a.action != 'none' and not a.notice.strip()) for a in self.answers):
            raise ValueError('Enter an answer label and an explanation for each action')
        return self


def rules_for(company):
    return json.loads(company.customer_questions or '[]') if company else []


def revision(rules):
    return hashlib.sha256(json.dumps(rules, sort_keys=True).encode()).hexdigest()


def matches(rule, row, catalog_names):
    if row.get('item_id') in rule.get('item_ids', []): return True
    name = normalized(row.get('name'))
    if name and name in {normalized(catalog_names.get(i, '')) for i in rule.get('item_ids', [])}: return True
    return any(word and (' ' + word + ' ') in (' ' + name + ' ') for word in map(normalized, rule.get('words', [])))


def questions(company, details, db):
    rules = rules_for(company)
    ids = {i for rule in rules for i in rule.get('item_ids', [])}
    names = {item.id: item.name for item in db.query(InventoryCatalogItem).filter(InventoryCatalogItem.id.in_(ids)).all()} if ids else {}
    rows = details.get('question_original_rows', details.get('spark_inventory_snapshot', []))
    answers = details.get('report_question_answers', {})
    result = []
    for rule in rules:
        if not rule.get('enabled'): continue
        for index, row in enumerate(rows):
            if not matches(rule, row, names): continue
            key = hashlib.sha256((revision(rule) + ':' + str(index) + ':' + revision(row)).encode()).hexdigest()
            saved = answers.get(key)
            result.append({'id': key, 'rule_id': rule['id'], 'item_index': index, 'name': row.get('name', 'Item'),
                'room': row.get('room', ''), 'quantity': row.get('amount', 1), 'question': rule['question'],
                'photo': rule.get('photo', True) and not row.get('item_id'), 'answers': rule['answers'], 'saved': saved})
    return result


def adjusted_inventory(company, details, rows, cuft, weight, db):
    from copy import deepcopy
    # Always calculate against the original report so repeated saves never subtract twice.
    details.setdefault('question_original_rows', deepcopy(rows))
    details.setdefault('question_original_cuft', cuft)
    details.setdefault('question_original_weight', weight)
    excluded = set()
    for question in questions(company, details, db):
        saved = question['saved'] or {}
        option = next((a for a in question['answers'] if a['id'] == saved.get('answer_id')), None)
        if option and option['action'] == 'exclude' and not saved.get('pending') and (not option.get('acknowledge') or saved.get('acknowledged')):
            excluded.add(question['item_index'])
    original = details['question_original_rows']
    kept = [deepcopy(row) for index, row in enumerate(original) if index not in excluded]
    volume = max(0, float(details['question_original_cuft'] or 0) - sum(float(row.get('cuft') or 0) for i, row in enumerate(original) if i in excluded))
    mass = max(0, float(details['question_original_weight'] or 0) - sum(float(row.get('weight') or 0) for i, row in enumerate(original) if i in excluded))
    details['question_excluded_items'] = [deepcopy(row) for i, row in enumerate(original) if i in excluded]
    return kept, volume, mass
