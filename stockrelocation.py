from flask import Blueprint, render_template, g, url_for, flash, redirect, \
    session, request, jsonify, abort
from ciclop.tryton import tryton
from ciclop.csrf import csrf
from ciclop.helpers import login_required
from flask_babel import gettext as _
from trytond.transaction import Transaction

stockrelocation = Blueprint('stockrelocation', __name__, template_folder='templates')

User = tryton.pool.get('res.user')
Cart = tryton.pool.get('stock.cart')
ShipmentOutCart = tryton.pool.get('stock.shipment.out.cart')
Location = tryton.pool.get('stock.location')
Relocation = tryton.pool.get('stock.relocation')
Product = tryton.pool.get('product.product')

@stockrelocation.route("/relocation/json/product", methods=["POST"], endpoint="product")
@login_required
@tryton.transaction()
@csrf.exempt
def product(lang):
    '''Get Product Info JSON'''

    product = request.json.get('product')

    warehouse = Transaction().context.get('stock_warehouse')
    if warehouse:
        warehouse = Location(warehouse)
    else:
        warehouse, = Location.search([
            ('type', '=', 'warehouse')
            ], limit=1)

    vals = {}

    if product:
        products = Product.search([
            ('rec_name', '=', product),
            ], limit=1)
        if products:
            product, = products
            relocation = Relocation()
            relocation.product = product
            relocation.warehouse = warehouse
            on_change = relocation.on_change_product()
            vals['quantity'] = int(on_change.quantity) if on_change.quantity else 0
            vals['from_location'] = on_change.from_location.id if on_change.from_location else None

    return jsonify(results=vals)

@stockrelocation.route("/relocation/save", methods=["POST"], endpoint="save")
@login_required
@tryton.transaction()
@csrf.exempt
def save(lang):
    '''Save'''

    context = Transaction().context

    company = None
    employee = None
    warehouse = None
    if context.get('company'):
        company = context['company']
    if context.get('employee'):
        employee = context['employee']
    if context.get('stock_warehouse'):
        warehouse = context['stock_warehouse']

    if not company or not employee or not warehouse:
        flash(_('Select an employee, a warehouse or company in your preferences.'))
        return redirect(url_for('.relocations', lang=g.language))

    data = {}
    if request.json: # JSON
        for d in request.json:
            data[d['name']] = d['value']
    elif request.method == 'POST': # POST
        for k, v in request.form.iteritems():
            data[k] = v

    if data: # save/confirm data
        qty = float(data['quantity'])
        if qty > 0:
            products = Product.search([
                ('rec_name', '=', data['product']),
                ], limit=1)
            if products:
                product, = products

                relocation = Relocation()
                relocation.planned_date = Relocation.default_planned_date()
                relocation.product = product
                on_change = relocation.on_change_product()
                relocation.uom = on_change.uom
                relocation.from_location = int(data['from_location'])
                relocation.to_location = int(data['to_location'])
                relocation.quantity = qty
                relocation.employee = employee
                relocation.warehouse = warehouse
                relocation.company = company
                relocation.save()
                flash(_('Created a new relocation "{product}" from '
                        '"{from_location}" to "{to_location}" '
                        '(Qty: {quantity}).').format(
                    product=relocation.product.rec_name,
                    from_location=relocation.from_location.rec_name,
                    to_location=relocation.to_location.rec_name,
                    quantity=int(qty),
                    ), 'success')
                if data.get('confirm'):
                    try:
                        Relocation.confirm([relocation])
                        flash(_('Confirmed new relocation "{product}". '
                                'A move was generated to new location.').format(
                            product=relocation.product.rec_name), 'success')
                    except Exception as e:
                        message = '. '.join(filter(None, list(e[1])))
                        flash(message, 'danger')
        elif qty == 0:
            flash(_('Qty is 0. Not created new relocation.'))
        else:
            flash(_('Not found product.'))

    if request.json:
        # Add JSON messages (success, warning)
        success = []
        warning = []
        for f in session.get('_flashes', []):
            if f[0] == 'success':
                success.append(f[1])
            else:
                warning.append(f[1])
        messages = {}
        messages['success'] = ",".join(success)
        messages['warning'] = ",".join(warning)

        session.pop('_flashes', None)
        return jsonify(result=True, messages=messages)

    return redirect(url_for('.relocations', lang=g.language))

@stockrelocation.route("/relocation/edit", methods=["GET", "POST"], endpoint="edit")
@login_required
@tryton.transaction()
@csrf.exempt
def edit(lang):
    '''Edit'''

    context = Transaction().context

    company = None
    employee = None
    warehouse = None
    if context.get('company'):
        company = context['company']
    if context.get('employee'):
        employee = context['employee']
    if context.get('stock_warehouse'):
        warehouse = context['stock_warehouse']

    if not company or not employee or not warehouse:
        flash(_('Select an employee, a warehouse or company in your preferences.'))
        return redirect(url_for('.relocations', lang=g.language))

    locations = Location.search([
        ('type', 'not in', ('warehouse', 'view')),
        ])
    default_to_location = Relocation.default_to_location()

    #breadcumbs
    breadcrumbs = [{
        'slug': None,
        'name': _('Stock'),
        }, {
        'slug': url_for('.relocations', lang=g.language),
        'name': _('Relocations'),
        }, {
        'slug': url_for('.edit', lang=g.language),
        'name': _('Edit'),
        }]

    return render_template('stock-relocation-edit.html',
        breadcrumbs=breadcrumbs,
        locations=locations,
        default_to_location=default_to_location,
        )

@stockrelocation.route("/relocation/confirm", methods=["POST"], endpoint="confirm")
@login_required
@tryton.transaction()
@csrf.exempt
def confirm(lang):
    '''Confirm'''

    employee = Relocation.default_employee()

    if request.method == 'POST':
        rlocs = [int(r) for r in request.form.getlist('relocation')]
        if rlocs:
            domain = [
                ('id', 'in', rlocs),
                ('state', '=', 'draft'),
                ]
            if employee:
                domain.append(('employee', '=', employee))
            relocations = Relocation.search(domain)
            try:
                Relocation.confirm(relocations)
                flash(_('Confirmed to move {total} product/s to new locations.').format(
                    total=len(relocations)), 'info')
            except Exception as e:
                message = '. '.join(filter(None, list(e[1])))
                flash(_('Error when confirm relocations: {e}').format(
                    e=message), 'danger')

    return redirect(url_for('.relocations', lang=g.language))

@stockrelocation.route("/relocation/delete", methods=["POST"], endpoint="delete")
@login_required
@tryton.transaction()
@csrf.exempt
def delete(lang):
    '''Delete'''

    employee = Relocation.default_employee()

    if request.method == 'POST':
        rlocs = [int(r) for r in request.form.getlist('relocation')]
        if rlocs:
            domain = [
                ('id', 'in', rlocs),
                ('state', '=', 'draft'),
                ]
            if employee:
                domain.append(('employee', '=', employee))
            relocations = Relocation.search(domain)
            try:
                Relocation.delete(relocations)
                flash(_('Deleted {total} draft location/s.').format(
                    total=len(relocations)), 'info')
            except Exception as e:
                message = '. '.join(filter(None, list(e[1])))
                flash(_('Error when delete relocations: {e}').format(
                    e=message), 'danger')

    return redirect(url_for('.relocations', lang=g.language))

@stockrelocation.route("/relocation/<int:id>", endpoint="relocation")
@login_required
@tryton.transaction()
def relocation(lang, id):
    '''Relocation'''
    relocations = Relocation.search([
        ('id', '=', id),
        ], limit=1)
    if not relocations:
        abort(404)

    relocation, = relocations
    
    #breadcumbs
    breadcrumbs = [{
        'slug': None,
        'name': _('Stock'),
        }, {
        'slug': url_for('.relocations', lang=g.language),
        'name': _('Relocations'),
        }, {
        'slug': url_for('.relocation', lang=g.language, id=relocation.id),
        'name': relocation.rec_name,
        },
        ]

    return render_template('stock-relocation.html',
        breadcrumbs=breadcrumbs,
        relocation=relocation,
        )

@stockrelocation.route("/relocation", endpoint="relocations")
@login_required
@tryton.transaction()
@csrf.exempt
def relocations(lang):
    '''Relocations'''
    
    employee = Relocation.default_employee()
    planned_date = Relocation.default_planned_date()

    domain = [('planned_date', '>=', planned_date)]
    if employee:
        domain.append(('employee', '=', employee))
    relocations = Relocation.search(domain)

    #breadcumbs
    breadcrumbs = [{
        'slug': None,
        'name': _('Stock'),
        }, {
        'slug': url_for('.relocations', lang=g.language),
        'name': _('Relocations'),
        }]

    return render_template('stock-relocations.html',
        breadcrumbs=breadcrumbs,
        relocations=relocations,
        )
