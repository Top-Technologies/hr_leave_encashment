# -*- coding: utf-8 -*-
from datetime import date
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class HrLeaveEncashment(models.Model):
    _name = 'hr.leave.encashment'
    _description = 'Leave Encashment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference',
        default=lambda s: _('New'),
        copy=False,
        readonly=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        tracking=True,
        default=lambda s: s.env.user.employee_id,
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        related='employee_id.department_id',
        store=True,
        readonly=True,
    )
    job_id = fields.Many2one(
        'hr.job',
        string='Job Position',
        related='employee_id.job_id',
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='employee_id.company_id',
        store=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
    )
    holiday_status_id = fields.Many2one(
        'hr.leave.type',
        string='Time Off Type',
        required=True,
        domain="[('encashable', '=', True)]",
        tracking=True,
    )
    date = fields.Date(
        string='Encashment Date',
        default=fields.Date.context_today,
        required=True,
    )

    # Leave Balance Information
    total_allocated_days = fields.Float(
        string='Total Allocated Days',
        compute='_compute_balance_details',
        digits=(16, 2),
    )
    previously_utilized_days = fields.Float(
        string='Previously Utilized Days',
        compute='_compute_balance_details',
        digits=(16, 2),
    )
    expired_days = fields.Float(
        string='Expired Days',
        compute='_compute_balance_details',
        digits=(16, 2),
    )
    days_available = fields.Float(
        string='Available Leave Balance',
        compute='_compute_balance_details',
        digits=(16, 2),
    )
    days_to_encash = fields.Float(
        string='Days to Encash',
        digits=(16, 2),
        tracking=True,
    )
    remaining_balance_after = fields.Float(
        string='Balance After Encashment',
        compute='_compute_remaining_balance_after',
        digits=(16, 2),
    )

    # Payroll Information
    basic_salary = fields.Monetary(
        string='Basic Salary',
        compute='_compute_payroll_details',
    )
    rate_divisor = fields.Float(
        string='Salary Divisor',
        compute='_compute_payroll_details',
    )
    daily_rate = fields.Monetary(
        string='Daily Rate',
        compute='_compute_payroll_details',
    )
    amount = fields.Monetary(
        string='Encashment Amount',
        compute='_compute_amount',
        store=True,
        tracking=True,
    )
    original_amount = fields.Monetary(
        string='Original Amount',
        readonly=True,
        copy=False,
        help="Encashment amount before payroll expiry.",
    )
    expired_amount = fields.Monetary(
        string='Expired Amount',
        readonly=True,
        copy=False,
        help="Amount zeroed out upon expiry.",
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('sent_to_payroll', 'Sent to Payroll'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
    ], string='Status', default='draft', tracking=True)

    payroll_status = fields.Selection([
        ('not_sent', 'Not Sent'),
        ('draft', 'Draft Payslip'),
        ('confirmed', 'Confirmed Payslip'),
        ('paid', 'Paid'),
        ('expired', 'Expired'),
    ], string='Payroll Status', default='not_sent', tracking=True)

    line_ids = fields.One2many(
        'hr.leave.encashment.line',
        'encashment_id',
        string='FIFO Allocation Lines',
    )
    payslip_id = fields.Many2one(
        'hr.payslip',
        string='Payroll Reference',
        readonly=True,
        copy=False,
    )
    approved_date = fields.Date(
        string='Approval Date',
        readonly=True,
        copy=False,
    )
    payroll_expiry_date = fields.Date(
        string='Payroll Expiry Deadline',
        tracking=True,
    )
    expired_by = fields.Many2one(
        'res.users',
        string='Expired By',
        readonly=True,
        copy=False,
    )
    expired_date = fields.Datetime(
        string='Expiry Date',
        readonly=True,
        copy=False,
    )
    expiry_reason = fields.Text(
        string='Expiry Reason',
        readonly=True,
        copy=False,
    )
    auto_generated = fields.Boolean(
        string='Auto Generated',
        readonly=True,
        copy=False,
    )

    @api.depends('employee_id', 'holiday_status_id', 'date', 'state')
    def _compute_balance_details(self):
        Alloc = self.env['hr.leave.allocation']
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.employee_id or not rec.holiday_status_id:
                rec.total_allocated_days = 0.0
                rec.previously_utilized_days = 0.0
                rec.expired_days = 0.0
                rec.days_available = 0.0
                continue

            allocs = Alloc.search([
                ('employee_id', '=', rec.employee_id.id),
                ('holiday_status_id', '=', rec.holiday_status_id.id),
                ('state', '=', 'validate'),
            ])
            rec.total_allocated_days = sum(allocs.mapped('number_of_days'))
            rec.previously_utilized_days = sum((a.consumed_leave_days or a.leaves_taken or 0.0) for a in allocs)
            rec.expired_days = sum(allocs.mapped('expired_days'))

            # Available balance = valid non-expired allocations, deducting leaves taken, encashed days, and expired days
            avail = 0.0
            valid_allocs = allocs.filtered(
                lambda a: a.date_from <= rec.date and (not a.date_to or a.date_to >= rec.date)
            )
            for a in valid_allocs:
                utilized = a.consumed_leave_days or a.leaves_taken or 0.0
                free = a.number_of_days - utilized - (a.encashed_days or 0.0) - (a.expired_days or 0.0)
                if free > 0:
                    avail += free

            # If current record is already approved or sent to payroll, keep its days in available
            if rec.state in ('approved', 'sent_to_payroll', 'paid'):
                avail += rec.days_to_encash

            rec.days_available = max(0.0, round(avail, 2))

    @api.depends('days_available', 'days_to_encash')
    def _compute_remaining_balance_after(self):
        for rec in self:
            rec.remaining_balance_after = max(0.0, round(rec.days_available - (rec.days_to_encash or 0.0), 2))

    @api.depends('employee_id', 'employee_id.contract_id.wage')
    def _compute_payroll_details(self):
        divisor_param = self.env['ir.config_parameter'].sudo().get_param(
            'hr_leave_encashment.rate_divisor', 30.0)
        try:
            divisor = float(divisor_param or 30.0)
        except (TypeError, ValueError):
            divisor = 30.0
        if divisor <= 0:
            divisor = 30.0

        for rec in self:
            contract = rec.employee_id.contract_id
            rec.basic_salary = contract.wage if contract else 0.0
            rec.rate_divisor = divisor
            rec.daily_rate = (rec.basic_salary / divisor) if divisor else 0.0

    @api.depends('days_to_encash', 'daily_rate', 'state')
    def _compute_amount(self):
        for rec in self:
            if rec.state == 'expired':
                rec.amount = 0.0
            else:
                rec.amount = round((rec.days_to_encash or 0.0) * (rec.daily_rate or 0.0), 2)

    @api.constrains('days_to_encash', 'state')
    def _check_days(self):
        for rec in self:
            if rec.days_to_encash < 0:
                raise ValidationError(_("Days to encash cannot be negative."))
            if rec.state in ('draft', 'submitted'):
                if rec.days_to_encash <= 0:
                    continue
                if rec.days_to_encash > rec.days_available + 1e-6:
                    raise ValidationError(_(
                        "Requested encashment (%(req)s days) exceeds the available leave balance (%(avail)s days).",
                        req=rec.days_to_encash, avail=rec.days_available))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.leave.encashment') or _('New')
            if not vals.get('payroll_expiry_date'):
                base_date = fields.Date.to_date(vals.get('date')) or fields.Date.context_today(self)
                vals['payroll_expiry_date'] = base_date + relativedelta(months=3)
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                continue
            if rec.days_to_encash <= 0:
                raise UserError(_("Please specify a valid number of days to encash (greater than 0)."))
            if rec.days_to_encash > rec.days_available + 1e-6:
                raise UserError(_(
                    "Requested encashment (%(req)s days) exceeds available balance (%(avail)s days).",
                    req=rec.days_to_encash, avail=rec.days_available))
            rec.state = 'submitted'

    def action_approve(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.state != 'submitted':
                continue
            rec._consume_fifo()
            rec.write({
                'state': 'approved',
                'approved_date': today,
                'payroll_status': 'not_sent',
                'payroll_expiry_date': today + relativedelta(months=3),
            })
            rec.message_post(body=_("Leave encashment approved for %s day(s) (%s %s).",
                                    rec.days_to_encash, rec.amount, rec.currency_id.name or ''))

    def action_cancel(self):
        for rec in self:
            if rec.state == 'paid' or rec.payroll_status == 'paid':
                raise UserError(_("A paid encashment cannot be cancelled."))
            if rec.state == 'expired':
                raise UserError(_("An expired encashment cannot be cancelled."))
            if rec.payslip_id and rec.payslip_id.state in ('done', 'paid'):
                raise UserError(_("This encashment is linked to a confirmed payslip (%s).", rec.payslip_id.name))
            if rec.payslip_id and rec.payslip_id.state in ('draft', 'verify'):
                # Safely remove input line from draft payslip
                input_type = self.env.ref('hr_leave_encashment.input_type_leave_encashment', raise_if_not_found=False)
                if input_type:
                    rec.payslip_id.input_line_ids.filtered(lambda l: l.input_type_id == input_type).unlink()

            rec._restore_allocations()
            rec.write({
                'state': 'cancelled',
                'payroll_status': 'not_sent',
                'payslip_id': False,
            })
            rec.message_post(body=_("Leave encashment cancelled and allocation balances restored."))

    def action_draft(self):
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_("Only cancelled encashments can be reset to draft."))
            rec.state = 'draft'

    def action_expire_payroll(self, reason=None):
        """
        Manually or automatically expire approved unpaid encashment:
        - Sets payable amount to zero
        - Maintains original_amount for audit
        - Sets state to 'expired' and payroll_status to 'expired'
        - Safely removes unpaid input from draft payslip
        """
        for rec in self:
            if rec.state == 'paid' or rec.payroll_status == 'paid':
                raise UserError(_("Cannot expire an encashment that has already been paid."))
            if rec.payslip_id and rec.payslip_id.state in ('done', 'paid'):
                raise UserError(_("Cannot expire an encashment whose payslip has already been processed/paid."))

            # Safely remove input from draft payslip
            if rec.payslip_id and rec.payslip_id.state in ('draft', 'verify'):
                input_type = self.env.ref('hr_leave_encashment.input_type_leave_encashment', raise_if_not_found=False)
                if input_type:
                    rec.payslip_id.input_line_ids.filtered(lambda l: l.input_type_id == input_type).unlink()

            orig = rec.amount
            rec.write({
                'state': 'expired',
                'payroll_status': 'expired',
                'original_amount': orig,
                'expired_amount': orig,
                'amount': 0.0,
                'expired_by': self.env.uid,
                'expired_date': fields.Datetime.now(),
                'expiry_reason': reason or _("Payroll expired by HR"),
                'payslip_id': False,
            })
            rec.message_post(body=_(
                "Encashment expired. Original amount %s %s set to 0.0. Reason: %s",
                orig, rec.currency_id.name or '', rec.expiry_reason
            ))

    def _consume_fifo(self):
        """
        Deducts days from valid allocations in FIFO order:
        1. Earliest expiry (date_to)
        2. Earliest start (date_from)
        3. Deterministic ID
        Does NOT alter number_of_days; uses hr.leave.encashment.line!
        """
        self.ensure_one()
        Alloc = self.env['hr.leave.allocation'].sudo()
        allocs = Alloc.search([
            ('employee_id', '=', self.employee_id.id),
            ('holiday_status_id', '=', self.holiday_status_id.id),
            ('state', '=', 'validate'),
            ('date_from', '<=', self.date),
            '|', ('date_to', '=', False), ('date_to', '>=', self.date),
        ])

        def fifo_key(a):
            dt = a.date_to or date.max
            df = a.date_from or (a.create_date.date() if a.create_date else date.min)
            return (dt, df, a.id)

        sorted_allocs = allocs.sorted(key=fifo_key)
        remaining = self.days_to_encash
        line_vals = []

        # Lock allocation records
        if sorted_allocs:
            self.env.cr.execute(
                'SELECT id FROM hr_leave_allocation WHERE id IN %s FOR UPDATE',
                [tuple(sorted_allocs.ids)]
            )

        for alloc in sorted_allocs:
            if remaining <= 0:
                break
            utilized = alloc.consumed_leave_days or alloc.leaves_taken or 0.0
            free = alloc.number_of_days - utilized - (alloc.encashed_days or 0.0) - (alloc.expired_days or 0.0)
            if free <= 0:
                continue

            take = min(free, remaining)
            vals = {
                'allocation_id': alloc.id,
                'days': take,
            }
            line_vals.append((0, 0, vals))
            alloc.message_post(body=_(
                "%(d)s day(s) encashed (%(ref)s).", d=take, ref=self.name))
            remaining -= take

        if remaining > 1e-6:
            raise UserError(_(
                "Not enough valid allocation to encash %s day(s). Available balance may have changed.", remaining))

        self.line_ids = line_vals

    def _restore_allocations(self):
        for rec in self:
            rec.line_ids.unlink()

    @api.model
    def _cron_expire_unpaid(self, months=3):
        """
        Scheduled action to expire approved unpaid encashments whose expiry date has passed.
        """
        today = fields.Date.context_today(self)
        limit = today - relativedelta(months=months)
        stale = self.search([
            ('state', 'in', ('approved', 'sent_to_payroll')),
            ('payroll_status', '!=', 'paid'),
            '|',
            ('payroll_expiry_date', '<=', today),
            '&', ('payroll_expiry_date', '=', False), ('approved_date', '<', limit),
        ])
        for rec in stale:
            # Skip if payslip is confirmed or paid
            if rec.payslip_id and rec.payslip_id.state in ('done', 'paid'):
                continue
            rec.action_expire_payroll(reason=_("Scheduled automatic expiry of unpaid encashment."))


class HrLeaveEncashmentLine(models.Model):
    _name = 'hr.leave.encashment.line'
    _description = 'Leave Encashment FIFO Line'
    _order = 'id desc'

    encashment_id = fields.Many2one(
        'hr.leave.encashment',
        string='Encashment Reference',
        required=True,
        ondelete='cascade',
    )
    allocation_id = fields.Many2one(
        'hr.leave.allocation',
        string='Leave Allocation',
        required=True,
        ondelete='cascade',
    )
    days = fields.Float(
        string='Encashed Days',
        required=True,
        digits=(16, 2),
    )
    date_to = fields.Date(
        string='Allocation Expiry Date',
        related='allocation_id.date_to',
        readonly=True,
    )
