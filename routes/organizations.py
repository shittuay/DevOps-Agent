"""
Organization and Multi-tenancy Routes
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, session
from flask_login import login_required, current_user
from functools import wraps

organizations_bp = Blueprint('organizations', __name__, url_prefix='/organizations')


def org_admin_required(f):
    """Decorator to require organization admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from services.multi_tenancy import MultiTenancyService
        org_id = kwargs.get('org_id') or request.view_args.get('org_id')
        if org_id:
            service = MultiTenancyService()
            member = service.get_membership(org_id, current_user.id)
            if not member or member.role not in ['owner', 'admin']:
                flash('You do not have admin access to this organization.', 'error')
                return redirect(url_for('organizations.list_organizations'))
        return f(*args, **kwargs)
    return decorated_function


@organizations_bp.route('/')
@login_required
def list_organizations():
    """List all organizations for current user"""
    from services.multi_tenancy import MultiTenancyService
    service = MultiTenancyService()
    memberships = service.get_user_organizations(current_user.id)
    return render_template('organizations/list.html', memberships=memberships)


@organizations_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_organization():
    """Create a new organization"""
    if request.method == 'POST':
        from services.multi_tenancy import MultiTenancyService
        service = MultiTenancyService()

        data = request.form.to_dict()

        org = service.create_organization(
            name=data.get('name', ''),
            owner_id=current_user.id,
            description=data.get('description'),
        )
        if org:
            flash('Organization created successfully!', 'success')
            return redirect(url_for('organizations.view_organization', org_id=org.id))
        else:
            flash('Failed to create organization.', 'error')

    return render_template('organizations/create.html')


@organizations_bp.route('/<int:org_id>')
@login_required
def view_organization(org_id):
    """View organization details"""
    from services.multi_tenancy import MultiTenancyService
    service = MultiTenancyService()

    org = service.get_organization(org_id)
    if not org:
        flash('Organization not found.', 'error')
        return redirect(url_for('organizations.list_organizations'))

    membership = service.get_membership(org_id, current_user.id)
    if not membership:
        flash('You are not a member of this organization.', 'error')
        return redirect(url_for('organizations.list_organizations'))

    members = service.get_organization_members(org_id)
    teams = service.get_organization_teams(org_id)

    sso_onboarding = None
    if membership.role in ('owner', 'admin'):
        from services import sso_onboarding as sso_ob
        sso_onboarding = sso_ob.get_onboarding_status(org)

    return render_template('organizations/view.html',
                         org=org,
                         membership=membership,
                         members=members,
                         teams=teams,
                         sso_onboarding=sso_onboarding)


@organizations_bp.route('/<int:org_id>/settings', methods=['GET', 'POST'])
@login_required
@org_admin_required
def organization_settings(org_id):
    """Organization settings"""
    from services.multi_tenancy import MultiTenancyService
    service = MultiTenancyService()

    org = service.get_organization(org_id)
    if not org:
        flash('Organization not found.', 'error')
        return redirect(url_for('organizations.list_organizations'))

    if request.method == 'POST':
        data = request.form.to_dict()
        updated = service.update_organization(org_id, data)
        if updated:
            flash('Organization updated successfully!', 'success')
        else:
            flash('Failed to update organization.', 'error')
        return redirect(url_for('organizations.organization_settings', org_id=org_id))

    return render_template('organizations/settings.html', organization=org)


@organizations_bp.route('/<int:org_id>/members')
@login_required
def list_members(org_id):
    """List organization members"""
    from services.multi_tenancy import MultiTenancyService
    service = MultiTenancyService()

    org = service.get_organization(org_id)
    membership = service.get_membership(org_id, current_user.id)

    if not membership:
        flash('You are not a member of this organization.', 'error')
        return redirect(url_for('organizations.list_organizations'))

    members = service.get_organization_members(org_id)
    invitations = []
    if membership.role in ['owner', 'admin']:
        invitations = service.get_pending_invitations(org_id)

    return render_template('organizations/members.html',
                         organization=org,
                         members=members,
                         invitations=invitations,
                         current_membership=membership)


@organizations_bp.route('/<int:org_id>/invite', methods=['POST'])
@login_required
@org_admin_required
def invite_member(org_id):
    """Invite a new member"""
    from services.multi_tenancy import MultiTenancyService
    service = MultiTenancyService()

    email = request.form.get('email')
    role = request.form.get('role', 'member')

    invitation = service.create_invitation(org_id, email, role, current_user.id)
    if invitation:
        flash(f'Invitation sent to {email}!', 'success')
    else:
        flash('Failed to send invitation.', 'error')

    return redirect(url_for('organizations.list_members', org_id=org_id))


@organizations_bp.route('/<int:org_id>/members/<int:user_id>/role', methods=['POST'])
@login_required
@org_admin_required
def update_member_role(org_id, user_id):
    """Update member role"""
    from services.multi_tenancy import MultiTenancyService
    service = MultiTenancyService()

    new_role = request.form.get('role')
    if service.update_member_role(org_id, user_id, new_role):
        flash('Member role updated!', 'success')
    else:
        flash('Failed to update member role.', 'error')

    return redirect(url_for('organizations.list_members', org_id=org_id))


@organizations_bp.route('/<int:org_id>/members/<int:user_id>/remove', methods=['POST'])
@login_required
@org_admin_required
def remove_member(org_id, user_id):
    """Remove a member from organization"""
    from services.multi_tenancy import MultiTenancyService
    service = MultiTenancyService()

    if service.remove_member(org_id, user_id):
        flash('Member removed from organization.', 'success')
    else:
        flash('Failed to remove member.', 'error')

    return redirect(url_for('organizations.list_members', org_id=org_id))


@organizations_bp.route('/<int:org_id>/teams')
@login_required
def list_teams(org_id):
    """List organization teams"""
    from services.multi_tenancy import MultiTenancyService
    service = MultiTenancyService()

    org = service.get_organization(org_id)
    membership = service.get_membership(org_id, current_user.id)

    if not membership:
        flash('You are not a member of this organization.', 'error')
        return redirect(url_for('organizations.list_organizations'))

    teams = service.get_organization_teams(org_id)

    return render_template('organizations/teams.html',
                         organization=org,
                         teams=teams,
                         current_membership=membership)


@organizations_bp.route('/<int:org_id>/teams/create', methods=['GET', 'POST'])
@login_required
@org_admin_required
def create_team(org_id):
    """Create a new team"""
    from services.multi_tenancy import MultiTenancyService
    service = MultiTenancyService()

    org = service.get_organization(org_id)

    if request.method == 'POST':
        data = {
            'organization_id': org_id,
            'name': request.form.get('name'),
            'description': request.form.get('description'),
            'created_by': current_user.id
        }

        team = service.create_team(
            org_id=org_id,
            name=request.form.get('name', ''),
            description=request.form.get('description'),
        )
        if team:
            flash('Team created successfully!', 'success')
            return redirect(url_for('organizations.view_team', org_id=org_id, team_id=team.id))
        else:
            flash('Failed to create team.', 'error')

    return render_template('organizations/create_team.html', org=org)


@organizations_bp.route('/<int:org_id>/teams/<int:team_id>')
@login_required
def view_team(org_id, team_id):
    """View team details"""
    from services.multi_tenancy import MultiTenancyService
    service = MultiTenancyService()

    org = service.get_organization(org_id)
    team = service.get_team(team_id)
    membership = service.get_membership(org_id, current_user.id)

    if not team or team.organization_id != org_id:
        flash('Team not found.', 'error')
        return redirect(url_for('organizations.list_teams', org_id=org_id))

    team_members = service.get_team_members(team_id)

    return render_template('organizations/view_team.html',
                         org=org,
                         team=team,
                         members=team_members,
                         current_membership=membership)


@organizations_bp.route('/<int:org_id>/sso', methods=['GET', 'POST'])
@login_required
@org_admin_required
def sso_settings(org_id):
    """SSO configuration"""
    import os
    from services.multi_tenancy import MultiTenancyService
    from services import sso_service
    service = MultiTenancyService()

    org = service.get_organization(org_id)

    if request.method == 'POST':
        ok, error = sso_service.save_config(org_id, request.form)
        if ok:
            flash('SSO configuration saved!', 'success')
        else:
            flash(error or 'Failed to save SSO configuration.', 'error')
        return redirect(url_for('organizations.sso_settings', org_id=org_id))

    sso_config = sso_service.get_admin_config(org)
    base = (os.environ.get('BASE_URL') or request.host_url).rstrip('/')

    from services import sso_onboarding as sso_ob
    onboarding = sso_ob.get_onboarding_status(org)

    from models import OrganizationDomain
    from services import domain_verification
    domains = []
    for row in OrganizationDomain.query.filter_by(organization_id=org_id).order_by(
            OrganizationDomain.domain).all():
        domains.append({
            'id': row.id,
            'domain': row.domain,
            'verified': row.verified,
            'verified_at': row.verified_at,
            'dns': domain_verification.dns_instructions(row),
        })

    return render_template(
        'organizations/sso.html', org=org, sso_config=sso_config, domains=domains,
        onboarding=onboarding,
        callback_url=base + url_for('sso_auth.callback'),
        saml_acs_url=base + url_for('sso_auth.saml_acs'),
        sp_entity_id=base + url_for('sso_auth.saml_metadata'),
        saml_metadata_url=base + url_for('sso_auth.saml_metadata'))


@organizations_bp.route('/<int:org_id>/sso/test', methods=['POST'])
@login_required
@org_admin_required
def test_sso(org_id):
    """Start a dry-run SSO login: validates the round-trip without provisioning."""
    from services.multi_tenancy import MultiTenancyService
    from services import sso_onboarding
    from routes.sso_auth import _begin_login

    org = MultiTenancyService().get_organization(org_id)
    if not org or not sso_onboarding.is_provider_configured(org.sso_config or {}):
        flash('Finish configuring the identity provider before testing.', 'error')
        return redirect(url_for('organizations.sso_settings', org_id=org_id))
    return _begin_login(org, next_url='', test=True)


@organizations_bp.route('/<int:org_id>/sso/domains/add', methods=['POST'])
@login_required
@org_admin_required
def add_sso_domain(org_id):
    """Claim a new email domain for SSO routing (starts unverified)."""
    from services import sso_service
    ok, error = sso_service.add_domain(org_id, request.form.get('domain', ''))
    flash('Domain added. Verify it via DNS to enable SSO routing.' if ok
          else (error or 'Failed to add domain.'), 'success' if ok else 'error')
    return redirect(url_for('organizations.sso_settings', org_id=org_id))


@organizations_bp.route('/<int:org_id>/sso/domains/<int:domain_id>/remove', methods=['POST'])
@login_required
@org_admin_required
def remove_sso_domain(org_id, domain_id):
    """Remove an email domain from the organization."""
    from services import sso_service
    if sso_service.remove_domain(org_id, domain_id):
        flash('Domain removed.', 'success')
    else:
        flash('Domain not found.', 'error')
    return redirect(url_for('organizations.sso_settings', org_id=org_id))


@organizations_bp.route('/<int:org_id>/sso/domains/<int:domain_id>/verify', methods=['POST'])
@login_required
@org_admin_required
def verify_sso_domain(org_id, domain_id):
    """Run a DNS TXT-record check to verify ownership of an SSO domain."""
    from models import OrganizationDomain
    from services import domain_verification

    row = OrganizationDomain.query.filter_by(id=domain_id, organization_id=org_id).first()
    if not row:
        flash('Domain not found.', 'error')
        return redirect(url_for('organizations.sso_settings', org_id=org_id))

    ok, message = domain_verification.verify_domain(row)
    flash(message, 'success' if ok else 'error')
    return redirect(url_for('organizations.sso_settings', org_id=org_id))


# API Endpoints
@organizations_bp.route('/api/organizations', methods=['GET'])
@login_required
def api_list_organizations():
    """API: List organizations"""
    from services.multi_tenancy import MultiTenancyService
    service = MultiTenancyService()
    memberships = service.get_user_organizations(current_user.id)

    return jsonify({
        'organizations': [{
            'id': m.organization.id,
            'name': m.organization.name,
            'slug': m.organization.slug,
            'role': m.role,
            'joined_at': m.joined_at.isoformat() if m.joined_at else None
        } for m in memberships]
    })


@organizations_bp.route('/api/organizations/<int:org_id>/switch', methods=['POST'])
@login_required
def api_switch_organization(org_id):
    """API: Switch active organization"""
    from services.multi_tenancy import MultiTenancyService
    from flask import session

    service = MultiTenancyService()
    membership = service.get_membership(org_id, current_user.id)

    if not membership:
        return jsonify({'error': 'Not a member of this organization'}), 403

    session['active_organization_id'] = org_id

    return jsonify({
        'success': True,
        'organization': {
            'id': membership.organization.id,
            'name': membership.organization.name
        }
    })


@organizations_bp.route('/invitation/<token>')
@login_required
def accept_invitation(token):
    """Accept an organization invitation"""
    from services.multi_tenancy import MultiTenancyService
    service = MultiTenancyService()

    membership = service.accept_invitation(token, current_user.id)
    if membership:
        flash(f'You have joined {membership.organization.name}!', 'success')
        return redirect(url_for('organizations.view_organization', org_id=membership.organization_id))
    else:
        flash('Invalid or expired invitation.', 'error')
        return redirect(url_for('organizations.list_organizations'))
