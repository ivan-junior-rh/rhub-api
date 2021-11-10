import logging

from connexion import problem

from rhub.lab import model
from rhub.api import db, DEFAULT_PAGE_LIMIT
from rhub.auth.keycloak import KeycloakClient
from rhub.auth import ADMIN_ROLE
from rhub.auth.utils import route_require_admin


logger = logging.getLogger(__name__)


def list_products(user, filter_, page=0, limit=DEFAULT_PAGE_LIMIT):
    products = model.Product.query

    if 'name' in filter_:
        products = products.filter(model.Product.name.ilike(filter_['name']))

    return {
        'data': [
            product.to_dict() for product in products.limit(limit).offset(page * limit)
        ],
        'total': products.count(),
    }


@route_require_admin
def create_product(body, user):
    query = model.Product.query.filter(model.Product.name == body['name'])
    if query.count() > 0:
        return problem(
            400, 'Bad Request',
            f'Product with name {body["name"]!r} already exists',
        )

    try:
        product = model.Product.from_dict(body)
    except ValueError as e:
        return problem(400, 'Bad Request', str(e))

    db.session.add(product)
    db.session.commit()
    logger.info(f'Product {product.name} (id {product.id}) created by user {user}')

    return product.to_dict()


def get_product(product_id):
    product = model.Product.query.get(product_id)
    if not product:
        return problem(404, 'Not Found', f'Product {product_id} does not exist')
    return product.to_dict()


@route_require_admin
def update_product(product_id, body, user):
    product = model.Product.query.get(product_id)
    if not product:
        return problem(404, 'Not Found', f'Product {product_id} does not exist')

    product.update_from_dict(body)

    db.session.commit()
    logger.info(f'Product {product.name} (id {product.id}) updated by user {user}')

    return product.to_dict()


@route_require_admin
def delete_product(product_id, user):
    product = model.Product.query.get(product_id)
    if not product:
        return problem(404, 'Not Found', f'Product {product_id} does not exist')

    if len(product.clusters) > 0:
        return problem(400, 'Bad Request',
                       f"Product {product_id} can't be deleted because it is used "
                       "by existing cluster")

    q = model.RegionProduct.query.filter(
        model.RegionProduct.product_id == product.id,
    )
    if q.count() > 0:
        for relation in q.all():
            db.session.delete(relation)
        db.session.flush()

    db.session.delete(product)
    db.session.commit()


def list_product_regions(keycloak: KeycloakClient, product_id, user,
                         page=0, limit=DEFAULT_PAGE_LIMIT):
    product = model.Product.query.get(product_id)
    if not product:
        return problem(404, 'Not Found', f'Product {product_id} does not exist')

    if keycloak.user_check_role(user, ADMIN_ROLE):
        def has_region_access(_):
            return True

    else:
        user_groups = [group['id'] for group in keycloak.user_group_list(user)]

        def has_region_access(region):
            return any([
                region.users_group is None,
                region.users_group in user_groups,
                region.owner_group in user_groups
            ])

    return [
        {'id': r.region_id, 'region': r.region.to_dict(), 'enabled': r.enabled}
        for r in product.regions_relation
        if has_region_access(r.region)
    ]