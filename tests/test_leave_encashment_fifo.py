# -*- coding: utf-8 -*-
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

from odoo.tests import tagged, TransactionCase
from odoo.exceptions import ValidationError, UserError


@tagged('post_install', '-at_install')
class TestLeaveEncashmentFIFO(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        # Employee & Contract
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Employee A',
            'company_id': cls.company.id,
        })
        cls.contract = cls.env['hr.contract'].create({
            'name': 'Contract - Employee A',
            'employee_id': cls.employee.id,
            'wage': 30000.0,
            'state': 'open',
            'date_start': date(2024, 1, 1),
            'company_id': cls.company.id,
        })
        cls.employee.contract_id = cls.contract.id

        # Leave Types
        cls.leave_type_2y = cls.env['hr.leave.type'].create({
            'name': 'Annual Leave 2Y',
            'requires_allocation': 'yes',
            'validity_years': 2,
            'encashable': True,
            'fifo_enabled': True,
            'leave_validation_type': 'no_validation',
            'allocation_validation_type': 'no_validation',
            'company_id': cls.company.id,
        })

    def test_01_two_year_allocation_expiry(self):
        """ Test automatic 2-year expiry calculation, scheduled expiry, and log generation """
        start_date = date(2023, 1, 1)
        expected_expiry = date(2024, 12, 31)

        alloc = self.env['hr.leave.allocation'].create({
            'name': '2023 Allocation',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'number_of_days': 20.0,
            'date_from': start_date,
        })
        alloc.action_validate()

        # Verify 2-year expiry date calculated
        self.assertEqual(alloc.date_to, expected_expiry)
        self.assertTrue(alloc.is_expired)

        # Run expiry cron
        self.env['hr.leave.allocation']._cron_log_expired_allocations()

        alloc.invalidate_recordset()
        self.assertTrue(alloc.expiry_processed)
        self.assertEqual(alloc.expired_days, 20.0)
        self.assertEqual(alloc.remaining_balance, 0.0)

        # Verify log entry in hr.leave.expiry.log
        log = self.env['hr.leave.expiry.log'].search([('allocation_id', '=', alloc.id)], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.expired_days, 20.0)
        self.assertEqual(log.employee_id, self.employee)

        # Verify that expired allocation cannot be encashed
        with self.assertRaises(ValidationError):
            self.env['hr.leave.encashment'].create({
                'employee_id': self.employee.id,
                'holiday_status_id': self.leave_type_2y.id,
                'date': date.today(),
                'days_to_encash': 5.0,
            })

    def test_02_fifo_normal_leave_utilization(self):
        """ Test FIFO consumption for normal leave requests across two allocations """
        # Allocation 1: 20 days (expires 2026)
        alloc1 = self.env['hr.leave.allocation'].create({
            'name': '2025 Allocation',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'number_of_days': 20.0,
            'date_from': date(2025, 1, 1),
            'date_to': date(2026, 12, 31),
        })
        alloc1.action_validate()

        # Allocation 2: 20 days (expires 2027)
        alloc2 = self.env['hr.leave.allocation'].create({
            'name': '2026 Allocation',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'number_of_days': 20.0,
            'date_from': date(2026, 1, 1),
            'date_to': date(2027, 12, 31),
        })
        alloc2.action_validate()

        # Request 25 days
        leave = self.env['hr.leave'].create({
            'name': 'Vacation 25 Days',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'request_date_from': date(2026, 6, 1),
            'request_date_to': date(2026, 7, 3),
            'number_of_days': 25.0,
        })
        leave.action_validate()

        # Check FIFO consumption tracking
        consumptions = self.env['hr.leave.allocation.consumption'].search([('leave_id', '=', leave.id)])
        self.assertEqual(len(consumptions), 2)

        c1 = consumptions.filtered(lambda c: c.allocation_id == alloc1)
        c2 = consumptions.filtered(lambda c: c.allocation_id == alloc2)

        # Alloc 1 consumed 20 days, Alloc 2 consumed 5 days
        self.assertEqual(c1.consumed_days, 20.0)
        self.assertEqual(c2.consumed_days, 5.0)

    def test_03_fifo_across_multiple_allocations(self):
        """ Test FIFO order across 3 allocations with ascending expiry dates """
        alloc1 = self.env['hr.leave.allocation'].create({
            'name': 'Alloc 1 (Exp Mid-2027)',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'number_of_days': 10.0,
            'date_from': date(2025, 1, 1),
            'date_to': date(2027, 6, 30),
        })
        alloc1.action_validate()
        alloc2 = self.env['hr.leave.allocation'].create({
            'name': 'Alloc 2 (Exp End-2027)',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'number_of_days': 10.0,
            'date_from': date(2025, 6, 1),
            'date_to': date(2027, 12, 31),
        })
        alloc2.action_validate()
        alloc3 = self.env['hr.leave.allocation'].create({
            'name': 'Alloc 3 (Exp End-2028)',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'number_of_days': 10.0,
            'date_from': date(2026, 1, 1),
            'date_to': date(2028, 12, 31),
        })
        alloc3.action_validate()

        leave = self.env['hr.leave'].create({
            'name': 'Trip 25 Days',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'request_date_from': date(2026, 7, 6),
            'request_date_to': date(2026, 8, 7),
            'number_of_days': 25.0,
        })
        leave.action_validate()

        consumptions = self.env['hr.leave.allocation.consumption'].search([('leave_id', '=', leave.id)])
        self.assertEqual(len(consumptions), 3)

        c1 = consumptions.filtered(lambda c: c.allocation_id == alloc1)
        c2 = consumptions.filtered(lambda c: c.allocation_id == alloc2)
        c3 = consumptions.filtered(lambda c: c.allocation_id == alloc3)

        self.assertEqual(c1.consumed_days, 10.0)
        self.assertEqual(c2.consumed_days, 10.0)
        self.assertEqual(c3.consumed_days, 5.0)

    def test_04_leave_cancellation_restores_balances(self):
        """ Test that cancelling a leave request clears FIFO consumption and restores balances """
        alloc = self.env['hr.leave.allocation'].create({
            'name': '2025 Alloc',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'number_of_days': 15.0,
            'date_from': date(2025, 1, 1),
            'date_to': date(2026, 12, 31),
        })
        alloc.action_validate()

        leave = self.env['hr.leave'].create({
            'name': 'Temporary Leave',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'request_date_from': date(2025, 3, 3),
            'request_date_to': date(2025, 3, 14),
            'number_of_days': 10.0,
        })
        leave.action_validate()

        self.assertEqual(len(leave.consumption_ids), 1)
        self.assertEqual(leave.consumption_ids.consumed_days, 10.0)

        # Refuse/cancel leave
        leave.action_refuse()
        self.assertEqual(len(leave.consumption_ids), 0)

    def test_05_leave_encashment_fifo(self):
        """ Test leave encashment FIFO deduction across allocations """
        alloc1 = self.env['hr.leave.allocation'].create({
            'name': 'Alloc 1',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'number_of_days': 10.0,
            'date_from': date(2025, 1, 1),
            'date_to': date(2026, 12, 31),
        })
        alloc1.action_validate()
        alloc2 = self.env['hr.leave.allocation'].create({
            'name': 'Alloc 2',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'number_of_days': 20.0,
            'date_from': date(2026, 1, 1),
            'date_to': date(2027, 12, 31),
        })
        alloc2.action_validate()

        enc = self.env['hr.leave.encashment'].create({
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'date': date(2026, 1, 15),
            'days_to_encash': 15.0,
        })

        self.assertEqual(enc.days_available, 30.0)
        self.assertEqual(enc.daily_rate, 1000.0) # 30,000 / 30 = 1000
        self.assertEqual(enc.amount, 15000.0)

        enc.action_submit()
        enc.action_approve()

        self.assertEqual(enc.state, 'approved')
        self.assertEqual(len(enc.line_ids), 2)

        line1 = enc.line_ids.filtered(lambda l: l.allocation_id == alloc1)
        line2 = enc.line_ids.filtered(lambda l: l.allocation_id == alloc2)

        self.assertEqual(line1.days, 10.0)
        self.assertEqual(line2.days, 5.0)

        alloc1.invalidate_recordset()
        alloc2.invalidate_recordset()
        self.assertEqual(alloc1.encashed_days, 10.0)
        self.assertEqual(alloc2.encashed_days, 5.0)

    def test_06_payroll_integration(self):
        """ Test encashment input line generation on payslip and marking paid upon payslip completion """
        struct = self.env.ref('hr_payroll.structure_002', raise_if_not_found=False)
        if not struct:
            struct = self.env['hr.payroll.structure'].create({
                'name': 'Regular Pay',
                'type_id': self.env['hr.payroll.structure.type'].create({'name': 'Salary'}).id,
            })

        alloc = self.env['hr.leave.allocation'].create({
            'name': 'Alloc for Payroll',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'number_of_days': 10.0,
            'date_from': date(2025, 1, 1),
            'date_to': date(2026, 12, 31),
        })
        alloc.action_validate()

        enc = self.env['hr.leave.encashment'].create({
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'date': date(2025, 2, 1),
            'days_to_encash': 5.0,
        })
        enc.action_submit()
        enc.action_approve()

        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Feb 2025',
            'employee_id': self.employee.id,
            'contract_id': self.contract.id,
            'struct_id': struct.id,
            'date_from': date(2025, 2, 1),
            'date_to': date(2025, 2, 28),
        })

        payslip.compute_sheet()
        enc.invalidate_recordset()
        self.assertEqual(enc.state, 'sent_to_payroll')
        self.assertEqual(enc.payroll_status, 'draft')
        self.assertEqual(enc.payslip_id, payslip)

        # Complete payslip
        payslip.action_payslip_done()
        enc.invalidate_recordset()
        self.assertEqual(enc.state, 'paid')
        self.assertEqual(enc.payroll_status, 'paid')

    def test_07_manual_payroll_expiry_wizard(self):
        """ Test manual payroll expiry via wizard, setting amount to zero and preserving original amount """
        alloc = self.env['hr.leave.allocation'].create({
            'name': 'Alloc',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'number_of_days': 10.0,
            'date_from': date(2025, 1, 1),
            'date_to': date(2026, 12, 31),
        })
        alloc.action_validate()

        enc = self.env['hr.leave.encashment'].create({
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'date': date(2025, 2, 1),
            'days_to_encash': 5.0,
        })
        enc.action_submit()
        enc.action_approve()

        self.assertEqual(enc.amount, 5000.0)

        wizard = self.env['hr.leave.payroll.expiry.wizard'].create({
            'encashment_id': enc.id,
            'expiry_reason': 'Unclaimed encashment expired by HR Policy.',
        })
        wizard.action_confirm_expiry()

        enc.invalidate_recordset()
        self.assertEqual(enc.state, 'expired')
        self.assertEqual(enc.payroll_status, 'expired')
        self.assertEqual(enc.amount, 0.0)
        self.assertEqual(enc.original_amount, 5000.0)
        self.assertEqual(enc.expired_amount, 5000.0)
        self.assertTrue(enc.expired_by)
        self.assertEqual(enc.expiry_reason, 'Unclaimed encashment expired by HR Policy.')

    def test_08_prevent_expiry_of_paid_encashment(self):
        """ Test that paid encashment cannot be expired or cancelled """
        alloc = self.env['hr.leave.allocation'].create({
            'name': 'Alloc Paid',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'number_of_days': 5.0,
            'date_from': date(2025, 1, 1),
            'date_to': date(2026, 12, 31),
        })
        alloc.action_validate()
        enc = self.env['hr.leave.encashment'].create({
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'date': date(2025, 1, 1),
            'days_to_encash': 5.0,
        })
        enc.action_submit()
        enc.action_approve()
        enc.write({'state': 'paid', 'payroll_status': 'paid'})

        with self.assertRaises(UserError):
            enc.action_expire_payroll()

        with self.assertRaises(UserError):
            enc.action_cancel()

    def test_09_automatic_payroll_expiry_cron(self):
        """ Test scheduled action _cron_expire_unpaid expiring past-deadline encashments """
        alloc = self.env['hr.leave.allocation'].create({
            'name': 'Alloc Cron',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'number_of_days': 10.0,
            'date_from': date(2024, 1, 1),
            'date_to': date(2025, 12, 31),
        })
        alloc.action_validate()
        enc = self.env['hr.leave.encashment'].create({
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'date': date(2024, 2, 1),
            'days_to_encash': 5.0,
            'payroll_expiry_date': date(2024, 5, 1), # in the past
        })
        enc.action_submit()
        enc.action_approve()
        enc.payroll_expiry_date = date(2024, 5, 1)

        self.env['hr.leave.encashment']._cron_expire_unpaid(months=3)

        enc.invalidate_recordset()
        self.assertEqual(enc.state, 'expired')
        self.assertEqual(enc.amount, 0.0)
        self.assertEqual(enc.original_amount, 5000.0)

    def test_10_overconsumption_and_balance_bounds(self):
        """ Test validation error when requesting or encashing beyond available balance """
        alloc = self.env['hr.leave.allocation'].create({
            'name': 'Alloc 10D',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_2y.id,
            'number_of_days': 10.0,
            'date_from': date(2025, 1, 1),
            'date_to': date(2026, 12, 31),
        })
        alloc.action_validate()

        with self.assertRaises(ValidationError):
            self.env['hr.leave.encashment'].create({
                'employee_id': self.employee.id,
                'holiday_status_id': self.leave_type_2y.id,
                'date': date(2025, 2, 1),
                'days_to_encash': 15.0, # Exceeds 10 available
            })
