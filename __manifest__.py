# -*- coding: utf-8 -*-
{
    'name': 'Leave Expiry, FIFO Utilization and Payroll Encashment',
    'version': '18.0.1.0.0',
    'category': 'Human Resources/Time Off',
    'summary': '2-Year Leave Expiry, Strict FIFO Leave Utilization, and Payroll Encashment with Expiry Management',
    'description': """
HR Leave Allocation, FIFO Utilization and Payroll Encashment
============================================================
Enhances Odoo Time Off and Payroll with:
1. Automatic 2-year leave allocation expiry.
2. Strict FIFO (First In, First Out) consumption for normal employee leave requests and encashment.
3. Allocation-level consumption tracking without double deductions.
4. Leave encashment conversion into payroll inputs with configurable daily rate divisor.
5. HR Payroll Expiry interface to expire approved unpaid encashments and set payable amounts to zero while preserving audit history.
6. Multi-company security, audit logs, and comprehensive reporting.
    """,
    'author': 'TopTec / Antigravity',
    'depends': [
        'hr_holidays',
        'hr_payroll',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/data.xml',
        'data/cron.xml',
        'wizard/hr_leave_payroll_expiry_wizard_views.xml',
        'views/encashment_views.xml',
        'views/leave_allocation_views.xml',
        'views/leave_reports.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
