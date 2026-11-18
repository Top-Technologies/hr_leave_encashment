# -*- coding: utf-8 -*-
from odoo import models, _


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def compute_sheet(self):
        Enc = self.env['hr.leave.encashment'].sudo()
        Input = self.env['hr.payslip.input'].sudo()
        input_type = self.env.ref(
            'hr_leave_encashment.input_type_leave_encashment', raise_if_not_found=False)

        if input_type:
            for slip in self.filtered(lambda s: s.state in ('draft', 'verify')):
                # Clear previous input lines for leave encashment
                slip.input_line_ids.filtered(lambda line: line.input_type_id == input_type).unlink()

                encs = Enc.search([
                    ('employee_id', '=', slip.employee_id.id),
                    ('state', 'in', ('approved', 'sent_to_payroll')),
                    ('payroll_status', 'not in', ('paid', 'expired')),
                    '|', ('payslip_id', '=', False), ('payslip_id', '=', slip.id),
                    ('date', '<=', slip.date_to),
                ])
                total_amount = sum(encs.mapped('amount'))
                if total_amount > 0:
                    Input.create({
                        'payslip_id': slip.id,
                        'input_type_id': input_type.id,
                        'amount': total_amount,
                    })
                    encs.write({
                        'payslip_id': slip.id,
                        'state': 'sent_to_payroll',
                        'payroll_status': 'draft',
                    })
        return super().compute_sheet()

    def action_payslip_done(self):
        res = super().action_payslip_done()
        self.env['hr.leave.encashment'].sudo().search([
            ('payslip_id', 'in', self.ids),
            ('state', 'in', ('approved', 'sent_to_payroll')),
            ('payroll_status', '!=', 'expired'),
        ]).write({
            'state': 'paid',
            'payroll_status': 'paid',
        })
        return res

    def action_payslip_cancel(self):
        res = super().action_payslip_cancel()
        # Release encashments when payslip is cancelled before payment
        self.env['hr.leave.encashment'].sudo().search([
            ('payslip_id', 'in', self.ids),
            ('state', '!=', 'expired'),
            ('payroll_status', '!=', 'paid'),
        ]).write({
            'payslip_id': False,
            'state': 'approved',
            'payroll_status': 'not_sent',
        })
        return res
