#models
from time import sleep
from callManager.models import (
        CallTime,
        LaborRequest,
        Event,
        LaborRequirement,
        LaborType,
        OneTimeLoginToken,
        PasswordResetToken,
        Steward,
        TimeChangeConfirmation,
        Worker,
        TimeEntry,
        MealBreak,
        SentSMS,
        ClockInToken,
        Owner,
        OwnerInvitation,
        Manager,
        ManagerInvitation,
        Company,
        StewardInvitation,
        TemporaryScanner,
        LocationProfile,
        )
#forms
from callManager.forms import (
        CallTimeForm,
        CompanyHoursForm,
        LaborTypeForm,
        LaborRequirementForm,
        EventForm,
        WorkerForm,
        WorkerFormLite,
        WorkerImportForm,
        WorkerRegistrationForm,
        SkillForm,
        OwnerRegistrationForm,
        ManagerRegistrationForm,
        CompanyForm,
        LocationProfileForm,
        AddWorkerForm
        )
# Django imports
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.http import base64
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST
from django.db.models import Sum, Q, Case, When, IntegerField, Count
from datetime import datetime, time, timedelta
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.urls import reverse
from django.contrib import messages
from django.contrib.messages import get_messages as django_get_messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import FileResponse
from django.db.models.functions import TruncDate, TruncMonth
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, SetPasswordForm
from django.contrib.auth.views import LoginView
from callManager.utils import send_custom_email

# Twilio imports
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from twilio.twiml.messaging_response import MessagingResponse

# repotlab imports for PDF generation
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import PageBreak, Table, TableStyle, Paragraph, SimpleDocTemplate, Table, TableStyle, Spacer, KeepTogether
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet

# other imports
import qrcode
from io import BytesIO, TextIOWrapper
import re
import random
import string
import uuid
from urllib.parse import urlencode, quote
from user_agents import parse

# posssibly imports
import pytz
import io

import logging

# Create a logger instance
logger = logging.getLogger('callManager')
@login_required
def call_time_report(request, slug):
    manager = request.user.manager
    company = manager.company
    call_time = get_object_or_404(CallTime, slug=slug, event__company=manager.company)
    labor_requests = LaborRequest.objects.filter(
        labor_requirement__call_time=call_time,
        confirmed=True).select_related('worker', 'labor_requirement__labor_type')
    labor_type_filter = request.GET.get('labor_type', 'All')
    if labor_type_filter != 'All':
        labor_requests = labor_requests.filter(labor_requirement__labor_type__id=labor_type_filter)
    confirmed_requests = labor_requests
    labor_types = LaborType.objects.filter(laborrequirement__call_time=call_time).distinct()
    format_type = request.GET.get('format', 'html')
    if format_type == 'pdf':
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), topMargin=0.25*inch, bottomMargin=0, leftMargin=0.5*inch, rightMargin=0.5*inch)
        styles = getSampleStyleSheet()
        elements = []
        # Header content (to be repeated on each page)
        def create_header():
            return KeepTogether([
                Paragraph(f"{company.name}", styles['Heading1']),
                Paragraph(f"{call_time.event.event_name}: {call_time.name} at {call_time.time.strftime('%I:%M %p')} on {call_time.date.strftime('%B %d, %Y')}", styles['Heading2']),
                Spacer(1, 0.2*inch)
            ])
        # Table headers
        headers = ['Name', 'Labor Type', 'Sign In', 'Sign Out', 'Meal Breaks', 'Hours', 'MP', 'Total Hours']
        table_data = []
        for req in confirmed_requests:
            time_entry = req.time_entries.first()
            if time_entry and time_entry.meal_breaks.exists():
                for meal_break in time_entry.meal_breaks.all():
                    meal_breaks = f"{meal_break.break_time.strftime('%I:%M %p')} ({meal_break.break_type.capitalize()})"
                    break
                meal_breaks = f"{meal_breaks}"
            else:
                meal_breaks = "None"
            row = [
                req.worker.name or "Unnamed Worker",
                req.labor_requirement.labor_type.name,
                time_entry.start_time.strftime('%I:%M %p') if time_entry and time_entry.start_time else "-",
                time_entry.end_time.strftime('%I:%M %p') if time_entry and time_entry.end_time else "-",
                meal_breaks,
                f"{time_entry.normal_hours:.2f}" if time_entry else "0.00",
                f"{time_entry.meal_penalty_hours:.2f}" if time_entry else "0.00",
                f"{time_entry.total_hours_worked:.2f}" if time_entry else "0.00"
            ]
            table_data.append(row)
        # Calculate column widths based on content
        c = canvas.Canvas(buffer, pagesize=landscape(letter))
        font_name = 'Helvetica'
        font_size = 10
        padding = 10  # Padding in points for each cell
        max_widths = [c.stringWidth(header, font_name, font_size) for header in headers]
        for row in table_data:
            for i, cell in enumerate(row):
                cell_width = c.stringWidth(str(cell), font_name, font_size)
                max_widths[i] = max(max_widths[i], cell_width)
        # Add padding and scale to fit page
        total_width = sum(max_widths) + 2 * padding * len(max_widths)
        page_width = landscape(letter)[0] - doc.leftMargin - doc.rightMargin
        if total_width > page_width:
            scale_factor = page_width / total_width
            max_widths = [w * scale_factor for w in max_widths]
        col_widths = [w + 2 * padding for w in max_widths]
        # Table styling
        table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ])
        # Calculate rows per page
        page_height = landscape(letter)[1]
        header_height = 1.5 * inch
        signature_height = 1.0 * inch
        available_height = page_height - header_height - signature_height - doc.topMargin - doc.bottomMargin
        row_height = 0.3 * inch
        rows_per_page = int(available_height // row_height)
        # Split data into pages
        data = [headers]
        for i in range(0, len(table_data), rows_per_page):
            elements.append(create_header())  # Add header to each page
            page_data = data + table_data[i:i + rows_per_page]
            table = Table(page_data, colWidths=col_widths)
            table.setStyle(table_style)
            elements.append(table)
            if i + rows_per_page < len(table_data):
                elements.append(PageBreak())
        doc.build(elements)
        buffer.seek(0)
        return FileResponse(buffer, as_attachment=True, filename=f"call_time_report_{slug}.pdf")
    context = {
        'call_time': call_time,
        'confirmed_requests': confirmed_requests,
        'labor_types': labor_types,
        'selected_labor_type': labor_type_filter
    }
    return render(request, 'callManager/call_time_report.html', context)

@login_required
def sms_usage_report(request):
    manager = request.user.manager
    daily_counts = SentSMS.objects.filter(
        company=manager.company).annotate(
        date=TruncDate('datetime_sent')).values(
        'company__name', 'date').annotate(
        count=Count('id')).order_by(
        'company__name', '-date')
    monthly_counts = SentSMS.objects.filter(
        company=manager.company).annotate(
        month=TruncMonth('datetime_sent')).values(
        'company__name', 'month').annotate(
        count=Count('id')).order_by(
        'company__name', '-month')
    monthly_daily_data = {}
    monthly_counts_with_keys = []
    for month_entry in monthly_counts:
        month = month_entry['month']
        key = month.strftime('%Y-%m')
        daily_data = SentSMS.objects.filter(
            company=manager.company,
            datetime_sent__year=month.year,
            datetime_sent__month=month.month).annotate(
            date=TruncDate('datetime_sent')).values(
            'date').annotate(
            count=Count('id')).order_by('date')
        monthly_daily_data[key] = [
            {'date': entry['date'].strftime('%Y-%m-%d'), 'count': entry['count']}
            for entry in daily_data]
        monthly_counts_with_keys.append({
            'company__name': month_entry['company__name'],
            'month': month,
            'count': month_entry['count'],
            'chart_key': key})
    context = {
        'daily_counts': daily_counts,
        'monthly_counts': monthly_counts_with_keys,
        'monthly_daily_data': monthly_daily_data,
        'company': manager.company}
    return render(request, 'callManager/sms_usage_report.html', context)


@login_required
def admin_sms_usage_report(request):
    if not hasattr(request.user, 'administrator'):
        return redirect('login')
    daily_counts = SentSMS.objects.annotate(
        date=TruncDate('datetime_sent')).values(
        'company__name', 'date').annotate(
        count=Count('id')).order_by(
        'company__name', '-date')
    monthly_counts = SentSMS.objects.annotate(
        month=TruncMonth('datetime_sent')).values(
        'company__name', 'month').annotate(
        count=Count('id')).order_by(
        'company__name', '-month')
    monthly_daily_data = {}
    monthly_counts_with_keys = []
    for month_entry in monthly_counts:
        month = month_entry['month']
        company_name = month_entry['company__name']
        key = f"{company_name}_{month.strftime('%Y-%m')}"
        daily_data = SentSMS.objects.filter(
            company__name=company_name,
            datetime_sent__year=month.year,
            datetime_sent__month=month.month).annotate(
            date=TruncDate('datetime_sent')).values(
            'date').annotate(
            count=Count('id')).order_by('date')
        monthly_daily_data[key] = [
            {'date': entry['date'].strftime('%Y-%m-%d'), 'count': entry['count']}
            for entry in daily_data]
        monthly_counts_with_keys.append({
            'company__name': company_name,
            'month': month,
            'count': month_entry['count'],
            'chart_key': key})
    context = {
        'daily_counts': daily_counts,
        'monthly_counts': monthly_counts_with_keys,
        'monthly_daily_data': monthly_daily_data}
    return render(request, 'callManager/admin_sms_usage_report.html', context)


@login_required
def event_workers_report(request):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    company = manager.company
    # Handle event_ids from POST (form submission) or GET (PDF download)
    event_ids = request.POST.getlist('event_ids') or request.GET.get('event_ids', '').split(',')
    event_ids = [id for id in event_ids if id]  # Remove empty strings
    print(f"Received event_ids: {event_ids}")  # Debug POST/GET data
    if not event_ids:
        messages.error(request, "No events selected.")
        return redirect('manager_dashboard')
    events = Event.objects.filter(id__in=event_ids, company=company)
    if not events.exists():
        messages.error(request, "No valid events found.")
        return redirect('manager_dashboard')
    
    # Gather workers by event and call time
    report_data = []
    for event in events.order_by('start_date'):
        for call_time in event.call_times.all().order_by('date', 'time'):
            labor_requests = LaborRequest.objects.filter(
                labor_requirement__call_time=call_time,
                confirmed=True
            ).select_related('worker', 'labor_requirement__labor_type')
            for req in labor_requests:
                time_entry = req.time_entries.first() if hasattr(req, 'time_entries') and req.time_entries.exists() else None
                report_data.append({
                    'event': event.event_name,
                    'call_time': f"{call_time.name} ({call_time.date} at {call_time.time.strftime('%I:%M %p')})",
                    'worker': req.worker.name or "Unnamed Worker",
                    'labor_type': req.labor_requirement.labor_type.name,
                    'sign_in': time_entry.start_time.strftime('%I:%M %p') if time_entry and time_entry.start_time else '-',
                    'sign_out': time_entry.end_time.strftime('%I:%M %p') if time_entry and time_entry.end_time else '-',
                    'meal_breaks': time_entry.meal_breaks.count() if time_entry and hasattr(time_entry, 'meal_breaks') else '-',
                    'total_hours': f"{time_entry.total_hours_worked:.2f}" if time_entry and time_entry.total_hours_worked is not None else '-'
                })

    format_type = request.GET.get('format', 'html')
    if format_type == 'pdf':
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), topMargin=0.5*inch, bottomMargin=1.5*inch, leftMargin=0.5*inch, rightMargin=0.5*inch)
        styles = getSampleStyleSheet()
        elements = []
        elements.append(Paragraph(f"Workers Report for {company.name}", styles['Heading1']))
        elements.append(Spacer(1, 0.2*inch))

        # Group data by event for PDF
        event_groups = {}
        for row in report_data:
            event_name = row['event']
            if event_name not in event_groups:
                event_groups[event_name] = []
            event_groups[event_name].append(row)

        # Calculate rows per page
        page_width = landscape(letter)[0] - doc.leftMargin - doc.rightMargin  # 10 inches
        colWidths = [130, 180, 130, 90, 70, 70, 70, 70]  # Adjusted to fit 10 inches
        page_height = landscape(letter)[1]
        header_height = 1.0 * inch
        signature_height = 1.0 * inch
        event_header_height = 0.5 * inch
        row_height = 0.3 * inch
        rows_per_page = int((page_height - header_height - signature_height - event_header_height) // row_height)

        # Generate tables for each event
        for event_name, rows in event_groups.items():
            elements.append(Paragraph(f"Event: {event_name}", styles['Heading2']))
            elements.append(Spacer(1, 0.1*inch))
            data = [['Event', 'Call Time', 'Worker', 'Labor Type', 'Sign In', 'Sign Out', 'Meal Breaks', 'Total Hours']]
            for row in rows:
                data.append([row['event'], row['call_time'], row['worker'], row['labor_type'], row['sign_in'], row['sign_out'], row['meal_breaks'], row['total_hours']])
            
            # Split event data into pages
            for i in range(0, len(data) - 1, rows_per_page):
                page_data = data[:1] + data[i + 1:i + 1 + rows_per_page]
                table = Table(page_data, colWidths=colWidths)
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                ]))
                elements.append(table)
                elements.append(Spacer(1, 0.5*inch))
                elements.append(Paragraph("Signature: _______________________________", styles['Normal']))
                if i + rows_per_page < len(data) - 1 or event_name != list(event_groups.keys())[-1]:
                    elements.append(PageBreak())
        
        doc.build(elements)
        buffer.seek(0)
        response = FileResponse(buffer, as_attachment=True, filename=f"workers_report_{company.name}.pdf")
        response['Content-Type'] = 'application/pdf'
        return response
    
    context = {
        'company': company,
        'events': events,
        'report_data': report_data,
        'event_ids': ','.join(event_ids)  # Pass event_ids for PDF link
    }
    return render(request, 'callManager/event_workers_report.html', context)

