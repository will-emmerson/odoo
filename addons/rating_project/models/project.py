# -*- coding: utf-8 -*-

from openerp import models, fields, api
from datetime import datetime, timedelta
from openerp.tools.translate import _

class ProjectTaskType(models.Model):
    _inherit = 'project.task.type'
    rating_template_id = fields.Many2one(
        'mail.template',
        string='Rating Email Template',
        domain=[('model', '=', 'rating.rating')],
        help="Select an email template. An email will be sent to the customer when the task reach this step.")
    auto_validation_kanban_state = fields.Boolean('Auto Kanban state validation', default=False,
        help="Automatically modify the kanban state when the customer reply to the feedback for this stage.\n"
            " * A great feedback from the customer will update the kanban state to 'ready for the new stage' (green bullet).\n"
            " * A medium or a bad feedback will set the kanban state to 'blocked' (red bullet).\n")

class Task(models.Model):
    _name = 'project.task'
    _inherit = ['project.task', 'rating.mixin']

    rating_latest = fields.Float(string="Latest Rating", related="rating_ids.rating", group_operator="avg", store=True)
    rating_feedback = fields.Text(string="Rating Feedback", related="rating_ids.feedback", store=True)
    rating_text = fields.Text(string="Rating Feedback", compute="_get_rating_text")

    # This method should be called once a day by the scheduler
    @api.model
    def _send_rating_all(self):
        periods = ['daily']
        if datetime.today().day in (1,15):
            periods.append('bimonthly')
        if datetime.today().day == 1:
            periods.append('monthly')
            if datetime.today().month in (1,4,7,10):
                periods.append('quarterly')
            if datetime.today().month in (1,):
                periods.append('yearly')
        if datetime.today().weekday() == 2:
            periods.append('weekly')
        project_ids = self.env['project.project'].search([('rating_status','=','periodic'),('rating_status_period','in',periods)])
        return self.search([('project_id', 'in', project_ids)])._send_rating_mail()

    @api.multi
    def _get_task_customer(self):
        self.ensure_one()
        return self.project_id.partner_id or None

    @api.multi
    def _send_rating_mail(self):
        for task in self:
            template = task.stage_id.rating_template_id
            if template:
                partner = self._get_task_customer()
                rated_partner_id = self.user_id.partner_id
                if partner and rated_partner_id:
                    self.rating_send_request(template, partner, rated_partner_id)
        return True

    @api.multi
    def write(self, values):
        result = super(Task, self).write(values)
        if 'stage_id' in values and values.get('stage_id'):
            self._send_rating_mail()
        return result

    @api.one
    def _get_rating_text(self):
        if (self.project_id.rating_status=='no') or (not self.rating_ids):
            self.rating_text = False
            return True
        self.rating_text = {
            0: _('Not happy'),
            5: _('Average'),
            10: _('Happy')
        }.get(self.rating_latest, _('Unknown rating'))

class Project(models.Model):
    _inherit = "project.project"

    @api.one
    @api.depends('tasks.rating_ids.rating')
    def _compute_rating_satisfaction(self):
        domain = [('create_date','>=',(datetime.today() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S'))]
        activity = self.tasks.rating_get_grades(domain)
        self.rating_satisfaction = activity['great'] * 100 / sum(activity.values()) if sum(activity.values()) else -1

    rating_satisfaction = fields.Integer(
        compute='_compute_rating_satisfaction', string='% Happy', store=True, default=-1)

    rating_status = fields.Selection([('no','No customer rating'), ('stage','On stage change'), ('periodic','Periodically')], 'Customer Ratings', default='no')
    rating_status_period = fields.Selection([
            ('daily','every day'), ('weekly','every week'), ('bimonthly','twice a month'), 
            ('monthly','one a month'), ('quarterly','quarterly'), ('yearly','yearly')
        ], 'Rating Frequency', default='monthly')

    @api.multi
    def action_view_task_rating(self):
        """ return the action to see all the rating about the tasks of the project """
        action = self.env['ir.actions.act_window'].for_xml_id('rating', 'action_view_rating')
        return dict(action, domain=[('rating', '!=', -1), ('res_id', 'in', self.tasks.ids), ('res_model', '=', 'project.task')])

    @api.multi
    def action_view_all_rating(self):
        """ return the action to see all the rating about the all sort of activity of the project (tasks, issues, ...) """
        return self.action_view_task_rating()


class Rating(models.Model):
    _inherit = "rating.rating"

    @api.model
    def apply_rating(self, rate, res_model=None, res_id=None, token=None):
        """ check if the auto_validation_kanban_state is activated. If so, apply the modification of the
            kanban state according to the given rating.
        """
        rating = super(Rating, self).apply_rating(rate, res_model, res_id, token)
        if rating.res_model == 'project.task':
            task = self.env[rating.res_model].sudo().browse(rating.res_id)
            if task.stage_id.auto_validation_kanban_state:
                if rating.rating > 5:
                    task.write({'kanban_state' : 'done'})
                else:
                    task.write({'kanban_state' : 'blocked'})
        return rating
