"""
PDF Compliance Report Service

Generates branded, downloadable compliance report PDFs.
"""
import io
from datetime import datetime
from src.utils.timeutils import utcnow

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    )
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


FRAMEWORK_NAMES = {
    'soc2': 'SOC 2 Type II',
    'hipaa': 'HIPAA',
    'pci_dss': 'PCI DSS',
    'gdpr': 'GDPR',
    'iso27001': 'ISO 27001',
    'nist': 'NIST CSF',
    'cis': 'CIS Benchmarks',
}

SEVERITY_COLORS = {
    'critical': '#ef4444',
    'high': '#f97316',
    'medium': '#eab308',
    'low': '#22c55e',
}


def generate_compliance_pdf(user_id, framework, report_data):
    """
    Generate a branded compliance report PDF.

    Args:
        user_id: The user ID
        framework: Framework name (soc2, hipaa, etc.)
        report_data: Dict with keys: overall_score, controls_passed, controls_failed,
                     findings (list of dicts), summary, generated_at

    Returns:
        BytesIO buffer containing the PDF
    """
    if not REPORTLAB_AVAILABLE:
        raise ImportError("reportlab is required for PDF generation. Install with: pip install reportlab")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch
    )

    styles = getSampleStyleSheet()
    orange = HexColor('#ff6b35')
    dark = HexColor('#1a1a2e')
    gray = HexColor('#64748b')
    light_gray = HexColor('#f1f5f9')

    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle', parent=styles['Title'],
        fontSize=24, textColor=orange, spaceAfter=6,
        fontName='Helvetica-Bold'
    )
    subtitle_style = ParagraphStyle(
        'CustomSubtitle', parent=styles['Normal'],
        fontSize=12, textColor=gray, spaceAfter=20
    )
    heading_style = ParagraphStyle(
        'CustomHeading', parent=styles['Heading2'],
        fontSize=16, textColor=dark, spaceBefore=20, spaceAfter=10,
        fontName='Helvetica-Bold'
    )
    body_style = ParagraphStyle(
        'CustomBody', parent=styles['Normal'],
        fontSize=10, textColor=dark, spaceAfter=6, leading=14
    )
    center_style = ParagraphStyle(
        'Center', parent=styles['Normal'],
        fontSize=10, textColor=gray, alignment=TA_CENTER
    )

    elements = []

    # Header
    fw_name = FRAMEWORK_NAMES.get(framework, framework.upper())
    elements.append(Paragraph("DevOps Agent", title_style))
    elements.append(Paragraph(f"{fw_name} Compliance Report", subtitle_style))
    elements.append(HRFlowable(width="100%", thickness=2, color=orange, spaceAfter=16))

    # Report metadata
    generated = report_data.get('generated_at', utcnow().isoformat())
    if isinstance(generated, str):
        try:
            generated = datetime.fromisoformat(generated).strftime('%B %d, %Y at %H:%M UTC')
        except (ValueError, TypeError):
            generated = str(generated)
    meta_data = [
        ['Framework:', fw_name],
        ['Generated:', generated],
        ['Report ID:', f"RPT-{user_id}-{framework.upper()}-{utcnow().strftime('%Y%m%d')}"],
    ]
    meta_table = Table(meta_data, colWidths=[1.2 * inch, 4.5 * inch])
    meta_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), gray),
        ('TEXTCOLOR', (1, 0), (1, -1), dark),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 20))

    # Score Summary
    elements.append(Paragraph("Compliance Summary", heading_style))
    score = report_data.get('overall_score', 0)
    passed = report_data.get('controls_passed', 0)
    failed = report_data.get('controls_failed', 0)
    total = passed + failed

    score_color = '#10b981' if score >= 80 else '#eab308' if score >= 60 else '#ef4444'

    summary_data = [
        ['Overall Score', 'Controls Passed', 'Controls Failed', 'Total Controls'],
        [f"{score}%", str(passed), str(failed), str(total)],
    ]
    summary_table = Table(summary_data, colWidths=[1.5 * inch] * 4)
    summary_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, 1), 18),
        ('TEXTCOLOR', (0, 0), (-1, 0), gray),
        ('TEXTCOLOR', (0, 1), (0, 1), HexColor(score_color)),
        ('TEXTCOLOR', (1, 1), (1, 1), HexColor('#10b981')),
        ('TEXTCOLOR', (2, 1), (2, 1), HexColor('#ef4444')),
        ('TEXTCOLOR', (3, 1), (3, 1), dark),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('BACKGROUND', (0, 0), (-1, -1), light_gray),
        ('BOX', (0, 0), (-1, -1), 0.5, HexColor('#e2e8f0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 12))

    # Summary text
    summary_text = report_data.get('summary', '')
    if summary_text:
        elements.append(Paragraph(summary_text, body_style))
    elements.append(Spacer(1, 10))

    # Findings Table
    findings = report_data.get('findings', [])
    if findings:
        elements.append(Paragraph(f"Findings ({len(findings)})", heading_style))

        header = ['Severity', 'Control', 'Description', 'Remediation']
        table_data = [header]

        for f in findings[:50]:  # Cap at 50 findings for PDF size
            severity = f.get('severity', 'medium').capitalize()
            control = f.get('control', f.get('title', 'N/A'))[:30]
            desc = f.get('description', 'N/A')[:80]
            remediation = f.get('remediation', 'N/A')[:80]
            table_data.append([severity, control, desc, remediation])

        findings_table = Table(
            table_data,
            colWidths=[0.8 * inch, 1.2 * inch, 2.2 * inch, 2.2 * inch]
        )
        findings_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0), dark),
            ('TEXTCOLOR', (0, 0), (-1, 0), HexColor('#ffffff')),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND', (0, 1), (-1, -1), HexColor('#ffffff')),
            ('BOX', (0, 0), (-1, -1), 0.5, HexColor('#e2e8f0')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, HexColor('#e2e8f0')),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#ffffff'), light_gray]),
        ]))
        elements.append(findings_table)
    else:
        elements.append(Paragraph("Findings", heading_style))
        elements.append(Paragraph("No findings detected. All controls passed.", body_style))

    # Footer
    elements.append(Spacer(1, 30))
    elements.append(HRFlowable(width="100%", thickness=1, color=HexColor('#e2e8f0'), spaceAfter=8))
    elements.append(Paragraph("Generated by DevOps Agent | Confidential", center_style))
    elements.append(Paragraph(f"Report generated on {utcnow().strftime('%Y-%m-%d %H:%M UTC')}", center_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer
