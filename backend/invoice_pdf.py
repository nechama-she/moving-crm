"""The invoice for a job: the company, who is billed and where, the estimate's price lines and its additional services and
fees (a fee with no charge shows $0.00), then each CRM payment with its confirmation number, and the balance due."""
from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from estimate_pdf import _kit, _price_table, _services_table, _services_total, _template, money


def build_invoice_pdf(data, payments, invoice_number, invoice_date: date):
    """data: the estimate as the customer signed it (or as it is now when not signed); payments: the CRM payments."""
    from inventory_pdf import company_logo_image
    styles, p, table = _kit(9)
    company = data.get('company_details') or {}
    estimate = data['estimate']
    total = Decimal(str(estimate.get('price') or 0))
    # The company on the left, the invoice number on the right.
    company_block = [p(value, 'NoteEstimate') for value in [
        ' - '.join(filter(None, [company.get('name') or data.get('company'), company.get('phone')])), company.get('office_address')] if value]
    logo = company_logo_image(company.get('logo'))
    header = Table([[[logo, *company_block] if logo else company_block, p(f'INVOICE {invoice_number}', 'CompanyEstimate')]],
                   colWidths=[322, 200], hAlign='LEFT')
    header.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                                ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('LINEBELOW', (0, 0), (-1, -1), .6, colors.HexColor('#bdc9d0')),
                                ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
    # Who is billed, the addresses, the invoice date and amount.
    def labeled(label, value):
        return [p(label, 'LabelEstimate'), p(value or 'Not set')]
    stops = '\n'.join(stop.get('address', '') for stop in data.get('stops') or [])
    details = Table([[
        labeled('BILLED TO', data.get('name')) + labeled('ORIGIN ADDRESS', data.get('pickup'))
        + labeled('DESTINATION ADDRESS', data.get('delivery')) + (labeled('STOPS', stops) if stops else []),
        labeled('INVOICE DATE', invoice_date.strftime('%m/%d/%Y')) + labeled('INVOICE AMOUNT', money(total))
        + labeled('MOVE DATE', str(data.get('move_date') or 'Not scheduled')),
    ]], colWidths=[322, 200], hAlign='LEFT')
    details.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
    story = [header, Spacer(1, 10), details, p('Charges', 'SectionEstimate')]
    story += _price_table(data, styles, p, table, total_label='TOTAL')
    # The additional services and fees, each with its charge: $0.00 where there is none.
    if _services_total(estimate)[0] or any(data.get(key) for key in ('extra_stops', 'elevator', 'long_carry', 'stairs', 'storage', 'shuttle')):
        story += [Paragraph('<a name="additional-services"/>Additional services and fees', styles['SectionEstimate']),
                  _services_table(data, p, table, styles, no_charge=money(0))]
    # Each payment with its confirmation number, then the balance.
    story.append(p('Payments', 'SectionEstimate'))
    body = [[p('DATE'), p('METHOD'), p('CONFIRMATION NUMBER'), p('AMOUNT', 'RightEstimate')]]
    body += [[p(payment.paid_at.strftime('%m/%d/%Y') if payment.paid_at else 'Not set'), p(payment.method or 'Not set'),
              p(payment.confirmation_number or '-'), p(money(payment.amount), 'RightEstimate')] for payment in payments]
    paid = sum((Decimal(str(payment.amount or 0)) for payment in payments), Decimal(0))
    totals = [('Invoice amount', money(total)), ('Total paid', '-' + money(paid) if paid else money(0)), ('Balance due', money(total - paid))]
    body += [[p(label), '', '', p(value, 'RightEstimate')] for label, value in totals]
    payment_table = table(body, [110, 130, 187, 95], header=True)
    payment_table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), .4, colors.HexColor('#bdc9d0'))]
                                      + [('SPAN', (0, len(body) - n), (2, len(body) - n)) for n in range(1, len(totals) + 1)]
                                      + [('BACKGROUND', (0, len(body) - 1), (-1, len(body) - 1), colors.HexColor('#edf2f5'))]))
    story.append(payment_table)
    output = BytesIO()
    _template(output, company).build(story)
    return output.getvalue()
