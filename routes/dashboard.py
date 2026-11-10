from flask import Blueprint, render_template, request
from flask_login import login_required
from services.report_service import ReportService

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@dashboard_bp.route('/dashboard')
@login_required
def index():
    days = request.args.get('days', 30, type=int)
    metrics = ReportService.get_dashboard_metrics(period_days=days)
    return render_template('dashboard/index.html', metrics=metrics, selected_days=days)
