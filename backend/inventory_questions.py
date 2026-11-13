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
    all_items: bool = False
    item_ids: list[str] = Field(default_factory=list, max_length=500)
    words: list[str] = Field(default_factory=list, max_length=50)
    photo: bool = True
    answers: list[AnswerOption] = Field(min_length=2, max_length=8)

    @model_validator(mode='after')
    def valid(self):
        if not self.title.strip() or not self.question.strip(): raise ValueError('Enter a title and question')
        if not self.all_items and not self.item_ids and not any(normalized(word) for word in self.words): raise ValueError('Select items or enter matching words')
        if len({a.id for a in self.answers}) != len(self.answers): raise ValueError('Answer IDs must be unique')
        if any(not a.label.strip() or (a.action != 'none' and not a.notice.strip()) for a in self.answers):
            raise ValueError('Enter an answer label and an explanation for each action')
        return self


def rules_for(company):
    return json.loads(company.customer_questions or '[]') if company else []


def revision(rules):
    return hashlib.sha256(json.dumps(rules, sort_keys=True).encode()).hexdigest()


def rule_revision(rule):
    # Adding the new default must not invalidate existing per-item answers.
    return revision({k: v for k, v in rule.items() if k != 'all_items' or v})


def selectable_items(rows):
    return [{'id': f'{index}:{unit}', 'item_index': index, 'unit_index': unit,
             'name': row.get('name', 'Item'), 'room': row.get('room', ''),
             'label': f"{row.get('name', 'Item')} ({unit + 1} of {max(1, int(row.get('amount') or 1))})"}
            for index, row in enumerate(rows) if row.get('going') is not False for unit in range(max(1, int(row.get('amount') or 1)))]


def matches(rule, row, catalog_names):
    if row.get('going') is False: return False
    if row.get('item_id') in rule.get('item_ids', []): return True
    name = normalized(row.get('name'))
    if name and name in {normalized(catalog_names.get(i, '')) for i in rule.get('item_ids', [])}: return True
    return any(word and (' ' + word + ' ') in (' ' + name + ' ') for word in map(normalized, rule.get('words', [])))


def question_key(rule, row):
    """An item question's id: the rule's revision and the row's question key, which stays with the row. A row moved
    into the inventory table keeps the key its questions always had (its position and contents in the report)."""
    return hashlib.sha256((rule_revision(rule) + ':' + str(row['question_key'])).encode()).hexdigest()


def questions(company, details, db, rows):
    """The company's questions about the inventory rows (the inventory table's rows, as list_rows reads them)."""
    rules = rules_for(company)
    ids = {i for rule in rules for i in rule.get('item_ids', [])}
    names = {item.id: item.name for item in db.query(InventoryCatalogItem).filter(InventoryCatalogItem.id.in_(ids)).all()} if ids else {}
    answers = details.get('report_question_answers', {})
    # After the list is edited, its rows no longer carry the report's own names, so no photos are offered.
    edited = bool(details.get('report_edited'))
    result = []
    for rule in rules:
        if not rule.get('enabled'): continue
        if rule.get('all_items'):
            key = 'all:' + rule_revision(rule)
            result.append({'id': key, 'rule_id': rule['id'], 'all_items': True,
                           'name': rule['title'], 'label': 'Your move', 'room': '', 'quantity': 0,
                           'question': rule['question'], 'photo': False, 'answers': rule['answers'],
                           'items': selectable_items(rows), 'saved': answers.get(key)})
            continue
        for index, row in enumerate(rows):
            if not matches(rule, row, names): continue
            key = question_key(rule, row)
            reference = None if edited else row.get('reference_name')
            # A report item the catalog did not match, or one it renamed (found by the report's name), has photos.
            report_photo = not edited and (bool(reference) or (row.get('manual') is False and not row.get('catalog_item_id')))
            count = max(1, int(row.get('amount') or 1))
            for unit in range(count):
                unit_key = key if count == 1 else f'{key}:{unit}'
                saved = answers.get(unit_key, answers.get(key))
                result.append({'id': unit_key, 'rule_id': rule['id'], 'item_index': index, 'unit_index': unit,
                    'reference_name': reference or row.get('name'), 'name': row.get('name', 'Item'), 'label': f"{row.get('name', 'Item')} ({unit + 1} of {count})" if count > 1 else row.get('name', 'Item'),
                    'room': row.get('room', ''), 'quantity': 1, 'question': rule['question'],
                    'photo': rule.get('photo', True) and report_photo, 'answers': rule['answers'], 'saved': saved})
    return result


def excluded_units(company, details, db, rows):
    """For each row (by position), how many of its units the saved answers take off the move."""
    excluded = set()
    for question in questions(company, details, db, rows):
        saved = question['saved'] or {}
        option = next((a for a in question['answers'] if a['id'] == saved.get('answer_id')), None)
        if option and option['action'] == 'exclude' and not saved.get('pending') and (not option.get('acknowledge') or saved.get('acknowledged')):
            if question.get('all_items'):
                selected = set(saved.get('selected_items', []))
                excluded.update((item['item_index'], item['unit_index']) for item in question['items'] if item['id'] in selected)
            else:
                excluded.add((question['item_index'], question['unit_index']))
    return [sum((index, unit) in excluded for unit in range(max(1, int(row.get('amount') or 1)))) for index, row in enumerate(rows)]


def apply_answers(company, details, job_id, db):
    """Record on each inventory row the units its answers take off the move. Returns whether any row changed.
    Does not commit."""
    from models import InventoryEditItem
    from inventory_edits import list_rows
    rows = list_rows(job_id, db)[0]
    counts = {row['inventory_row_id']: count for row, count in zip(rows, excluded_units(company, details, db, rows))}
    changed = False
    for item in db.query(InventoryEditItem).filter_by(job_id=job_id).all():
        if (item.excluded_quantity or 0) != counts.get(item.id, 0):
            item.excluded_quantity = counts.get(item.id, 0)
            changed = True
    db.flush()
    return changed


def _same_item(row):
    return (row.get('name'), row.get('room'), row.get('amount'), str(row.get('unit_cuft')), row.get('going') is not False,
            row.get('catalog_item_id'))


def carried_answers(company, previous_answers, old_rows, new_rows, db):
    """A new report: the answers that carry over. An item the customer kept keeps its answers (its question key stays);
    a report item the new report has again, unchanged, gets its earlier answer when there is no doubt which it was."""
    old_state = {'report_question_answers': previous_answers}
    old_questions = questions(company, old_state, db, old_rows)
    fresh = questions(company, {}, db, new_rows)
    carried = {}
    old_keys = {question['id'] for question in old_questions}
    for new in fresh:
        if new['id'] in old_keys:
            saved = next(old['saved'] for old in old_questions if old['id'] == new['id'])
            if saved:
                carried[new['id']] = saved
            continue
        if new.get('all_items'):
            continue
        candidates = [old for old in old_questions if not old.get('all_items')
                      and old['rule_id'] == new['rule_id'] and old['unit_index'] == new['unit_index']
                      and _same_item(old_rows[old['item_index']]) == _same_item(new_rows[new['item_index']])]
        # Do not guess which identical item an answer belonged to.
        if len(candidates) == 1 and candidates[0].get('saved'):
            carried[new['id']] = candidates[0]['saved']
    # A whole-move answer picks items by position: it carries over only when the list is unchanged.
    if [_same_item(row) for row in old_rows] == [_same_item(row) for row in new_rows]:
        for key, saved in previous_answers.items():
            if key.startswith('all:'):
                carried[key] = saved
    return carried
