from fpdf import FPDF
import os
from datetime import datetime

# Path to a Unicode-compatible font (standard on Windows)
FONT_PATH = r"C:\Windows\Fonts\arial.ttf"

class ReportPDF(FPDF):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if os.path.exists(FONT_PATH):
            self.add_font("ArialUnicode", "", FONT_PATH)
            self.add_font("ArialUnicode", "B", FONT_PATH)
            self.add_font("ArialUnicode", "I", FONT_PATH)
            self.main_font = "ArialUnicode"
        else:
            self.main_font = "helvetica"

    def header(self):
        self.set_font(self.main_font, 'B', 15)
        self.cell(0, 10, 'Monthly Expense Report', align='C', new_x="LMARGIN", new_y="NEXT")
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font(self.main_font, 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')

def sanitize_text(text, font_available=False):
    """If font is available, we don't need to be as aggressive, but we still handle unknown encoding issues."""
    if not text:
        return ""
    if font_available:
        # fpdf2 handles utf-8 with ttf fonts
        return str(text)
    return str(text).encode('latin-1', 'replace').decode('latin-1')

def generate_pdf_report(user_id, expenses, currency, month_name, budget=0, limits=None):
    try:
        return _create_pdf_report(user_id, expenses, currency, month_name, budget, limits)
    except Exception as e:
        # Emergency Fallback: If Unicode/Arial fails, force everything to plain ASCII/Latin-1
        print(f"[PDF] Error during high-fidelity generation: {e}. Falling back to emergency mode.")
        return _create_pdf_report(user_id, expenses, currency, month_name, budget, limits, force_ascii=True)

def _create_pdf_report(user_id, expenses, currency, month_name, budget=0, limits=None, force_ascii=False):
    pdf = ReportPDF()
    # If font is missing OR we are in emergency fallback mode, use Helvetica
    has_font = pdf.main_font == "ArialUnicode" and not force_ascii
    
    if force_ascii:
        pdf.main_font = "helvetica"
        
    pdf.add_page()
    pdf.set_font(pdf.main_font, '', 12)
    
    currency = sanitize_text(currency, has_font)
    month_name = sanitize_text(month_name, has_font)
    
    pdf.cell(0, 10, f'User ID: {user_id}', new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 10, f'Report Period: {month_name}', new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 10, f'Total Expenses: {len(expenses)}', new_x="LMARGIN", new_y="NEXT")
    
    if budget > 0:
        total_spent = sum(e['amount'] for e in expenses)
        pdf.cell(0, 10, f'Monthly Budget: {budget:.2f} {currency}', new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 10, f'Total Spent: {total_spent:.2f} {currency}', new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 10, f'Remaining: {(budget - total_spent):.2f} {currency}', new_x="LMARGIN", new_y="NEXT")
    
    pdf.ln(5)

    if limits:
        pdf.set_font(pdf.main_font, 'B', 12)
        pdf.cell(0, 10, 'Category Limits & Spending:', new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(pdf.main_font, '', 11)
        # Calculate spending per category
        cat_spend = {}
        for e in expenses:
            cat = e['category'].lower()
            cat_spend[cat] = cat_spend.get(cat, 0) + e['amount']
        
        for cat, limit in limits.items():
            spent = cat_spend.get(cat.lower(), 0)
            status = "OK" if spent <= limit else "OVER"
            cat_name = sanitize_text(cat.capitalize(), has_font)
            bullet = "•" if has_font else "-"
            pdf.cell(0, 8, f'{bullet} {cat_name}: {spent:.2f} / {limit:.2f} {currency} ({status})', new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

    # Table Header
    pdf.set_font(pdf.main_font, 'B', 12)
    pdf.cell(40, 10, 'Date', border=1)
    pdf.cell(50, 10, 'Category', border=1)
    pdf.cell(100, 10, f'Note / Description', border=1, new_x="LMARGIN", new_y="NEXT")
    
    # Table Content
    pdf.set_font(pdf.main_font, '', 10)
    for ex in expenses:
        date = ex['date'][:10]
        cat = sanitize_text(ex['category'].capitalize(), has_font)
        amt = ex['amount']
        note_text = ex.get('note') or ''
        note = sanitize_text(f"{note_text} ({amt:.2f} {currency})", has_font)
        
        pdf.cell(40, 10, date, border=1)
        pdf.cell(50, 10, cat, border=1)
        pdf.cell(100, 10, note, border=1, new_x="LMARGIN", new_y="NEXT")
        
    pdf.ln(5)
    pdf.set_font(pdf.main_font, 'B', 12)
    total_amt = sum(e['amount'] for e in expenses)
    pdf.cell(0, 10, f'Final Total: {total_amt:.2f} {currency}', new_x="LMARGIN", new_y="NEXT")
    
    reports_dir = "reports"
    os.makedirs(reports_dir, exist_ok=True)
    file_path = os.path.join(reports_dir, f"{user_id}_report_{month_name.replace(' ', '_')}.pdf")
    pdf.output(file_path)
    return file_path
