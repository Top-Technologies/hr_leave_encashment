# -*- coding: utf-8 -*-
from odoo import fields, models


class HrLeaveType(models.Model):
    _inherit = 'hr.leave.type'

    validity_years = fields.Integer(
        string='Allocation Validity (Years)',
        default=2,
        help="If greater than 0, every new allocation of this type automatically "
             "expires after this many years from start date. 0 = no automatic expiry (default is 2).",
    )
    encashable = fields.Boolean(
        string='Encashable',
        default=False,
        help="Employees/HR can convert unused days of this type into payroll.",
    )
    fifo_enabled = fields.Boolean(
        string='FIFO Enabled',
        default=True,
        help="Enables FIFO (First In, First Out) consumption for employee leave utilization.",
    )
