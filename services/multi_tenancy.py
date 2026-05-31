"""
Multi-tenancy and Organization Service for DevOps Agent.

Provides team workspaces, organization management, and SSO integration.
Uses database persistence for all data.
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from enum import Enum
import secrets
import re

logger = logging.getLogger(__name__)


class OrgRole(Enum):
    """Organization-level roles."""
    OWNER = 'owner'
    ADMIN = 'admin'
    MEMBER = 'member'
    BILLING = 'billing'
    VIEWER = 'viewer'


class TeamRole(Enum):
    """Team-level roles."""
    LEAD = 'lead'
    MEMBER = 'member'
    VIEWER = 'viewer'


class SSOProvider(Enum):
    """Supported SSO providers."""
    OKTA = 'okta'
    AZURE_AD = 'azure_ad'
    GOOGLE = 'google'
    GITHUB = 'github'
    SAML = 'saml'
    OIDC = 'oidc'


class MultiTenancyService:
    """Service for managing multi-tenancy features with database persistence."""

    def __init__(self, user_id: Optional[int] = None):
        self.user_id = user_id

    def _get_db(self):
        """Get database session."""
        from models import db
        return db

    def _get_org_model(self):
        """Get Organization model."""
        from models import Organization
        return Organization

    def _get_member_model(self):
        """Get OrganizationMember model."""
        from models import OrganizationMember
        return OrganizationMember

    def _get_team_model(self):
        """Get Team model."""
        from models import Team
        return Team

    def _get_team_member_model(self):
        """Get TeamMember model."""
        from models import TeamMember
        return TeamMember

    def _generate_slug(self, name: str) -> str:
        """Generate URL-safe slug from name."""
        slug = name.lower().strip()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        slug = slug.strip('-')
        return slug

    # Organization Management

    def create_organization(self, name: str, owner_id: int, description: str = None) -> Any:
        """Create a new organization."""
        Organization = self._get_org_model()
        OrganizationMember = self._get_member_model()
        db = self._get_db()

        # Generate unique slug
        base_slug = self._generate_slug(name)
        slug = base_slug
        counter = 1
        while Organization.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{counter}"
            counter += 1

        org = Organization(
            name=name,
            slug=slug,
            description=description,
            owner_id=owner_id,
            is_active=True
        )
        db.session.add(org)
        db.session.flush()

        # Add owner as member
        owner_member = OrganizationMember(
            organization_id=org.id,
            user_id=owner_id,
            role='owner',
            accepted_at=datetime.utcnow()
        )
        db.session.add(owner_member)
        db.session.commit()

        logger.info(f"Created organization: {name} (slug: {slug})")
        return org

    def get_organization(self, org_id: int) -> Optional[Any]:
        """Get organization by ID."""
        Organization = self._get_org_model()
        return Organization.query.get(org_id)

    def get_organization_by_slug(self, slug: str) -> Optional[Any]:
        """Get organization by slug."""
        Organization = self._get_org_model()
        return Organization.query.filter_by(slug=slug, is_active=True).first()

    def get_user_organizations(self, user_id: int) -> List[Any]:
        """Get all organizations for a user."""
        OrganizationMember = self._get_member_model()
        memberships = OrganizationMember.query.filter_by(
            user_id=user_id,
            is_active=True
        ).all()
        return [m for m in memberships if m.organization and m.organization.is_active]

    def update_organization(self, org_id: int, updates: Dict) -> Optional[Any]:
        """Update organization details."""
        db = self._get_db()
        org = self.get_organization(org_id)
        if not org:
            return None

        if 'name' in updates:
            org.name = updates['name']
        if 'description' in updates:
            org.description = updates['description']
        if 'billing_email' in updates:
            org.billing_email = updates['billing_email']
        if 'settings' in updates:
            org.settings = updates['settings']

        db.session.commit()
        return org

    def delete_organization(self, org_id: int) -> bool:
        """Soft delete an organization."""
        db = self._get_db()
        org = self.get_organization(org_id)
        if org:
            org.is_active = False
            db.session.commit()
            logger.info(f"Deleted organization: {org.name}")
            return True
        return False

    # Membership Management

    def get_membership(self, org_id: int, user_id: int) -> Optional[Any]:
        """Get user's membership in an organization."""
        OrganizationMember = self._get_member_model()
        return OrganizationMember.query.filter_by(
            organization_id=org_id,
            user_id=user_id,
            is_active=True
        ).first()

    def get_organization_members(self, org_id: int) -> List[Any]:
        """Get all members of an organization."""
        OrganizationMember = self._get_member_model()
        return OrganizationMember.query.filter_by(
            organization_id=org_id,
            is_active=True
        ).all()

    def add_member(self, org_id: int, user_id: int, role: str = 'member',
                   invited_by: int = None) -> Any:
        """Add a member to an organization."""
        OrganizationMember = self._get_member_model()
        db = self._get_db()

        # Check if already a member
        existing = self.get_membership(org_id, user_id)
        if existing:
            return existing

        member = OrganizationMember(
            organization_id=org_id,
            user_id=user_id,
            role=role,
            invited_by=invited_by,
            invited_at=datetime.utcnow() if invited_by else None,
            accepted_at=datetime.utcnow(),
            is_active=True
        )
        db.session.add(member)
        db.session.commit()

        logger.info(f"Added user {user_id} to org {org_id} as {role}")
        return member

    def update_member_role(self, org_id: int, user_id: int, new_role: str) -> Optional[Any]:
        """Update a member's role."""
        db = self._get_db()
        member = self.get_membership(org_id, user_id)
        if member:
            member.role = new_role
            db.session.commit()
            return member
        return None

    def remove_member(self, org_id: int, user_id: int) -> bool:
        """Remove a member from an organization."""
        db = self._get_db()
        member = self.get_membership(org_id, user_id)
        if member:
            member.is_active = False
            db.session.commit()
            logger.info(f"Removed user {user_id} from org {org_id}")
            return True
        return False

    # Invitation Management

    def create_invitation(self, org_id: int, email: str, role: str,
                          invited_by: int) -> Any:
        """Create an invitation to join an organization."""
        OrganizationMember = self._get_member_model()
        db = self._get_db()

        token = secrets.token_urlsafe(32)

        invitation = OrganizationMember(
            organization_id=org_id,
            user_id=None,  # Will be set when invitation is accepted
            role=role,
            invited_by=invited_by,
            invited_at=datetime.utcnow(),
            invitation_token=token,
            is_active=False  # Not active until accepted
        )
        db.session.add(invitation)
        db.session.commit()

        logger.info(f"Created invitation to org {org_id} for {email}")
        return {'token': token, 'email': email, 'org_id': org_id, 'role': role}

    def accept_invitation(self, token: str, user_id: int) -> Optional[Any]:
        """Accept an invitation."""
        OrganizationMember = self._get_member_model()
        db = self._get_db()

        invitation = OrganizationMember.query.filter_by(
            invitation_token=token,
            is_active=False
        ).first()

        if not invitation:
            return None

        # Check if already a member
        existing = self.get_membership(invitation.organization_id, user_id)
        if existing:
            db.session.delete(invitation)
            db.session.commit()
            return existing

        invitation.user_id = user_id
        invitation.accepted_at = datetime.utcnow()
        invitation.is_active = True
        invitation.invitation_token = None
        db.session.commit()

        logger.info(f"User {user_id} accepted invitation to org {invitation.organization_id}")
        return invitation

    def get_pending_invitations(self, org_id: int) -> list:
        """Return all pending (unaccepted) invitations for an organization."""
        OrganizationMember = self._get_member_model()
        return OrganizationMember.query.filter_by(
            organization_id=org_id,
            is_active=False
        ).filter(OrganizationMember.invitation_token.isnot(None)).all()

    # Team Management

    def create_team(self, org_id: int, name: str, description: str = None) -> Any:
        """Create a new team."""
        Team = self._get_team_model()
        db = self._get_db()

        team = Team(
            organization_id=org_id,
            name=name,
            description=description
        )
        db.session.add(team)
        db.session.commit()

        logger.info(f"Created team: {name} in org {org_id}")
        return team

    def get_team(self, team_id: int) -> Optional[Any]:
        """Get team by ID."""
        Team = self._get_team_model()
        return Team.query.get(team_id)

    def get_organization_teams(self, org_id: int) -> List[Any]:
        """Get all teams in an organization."""
        Team = self._get_team_model()
        return Team.query.filter_by(organization_id=org_id).all()

    def update_team(self, team_id: int, updates: Dict) -> Optional[Any]:
        """Update team details."""
        db = self._get_db()
        team = self.get_team(team_id)
        if not team:
            return None

        if 'name' in updates:
            team.name = updates['name']
        if 'description' in updates:
            team.description = updates['description']

        db.session.commit()
        return team

    def delete_team(self, team_id: int) -> bool:
        """Delete a team."""
        db = self._get_db()
        team = self.get_team(team_id)
        if team:
            db.session.delete(team)
            db.session.commit()
            logger.info(f"Deleted team: {team.name}")
            return True
        return False

    # Team Membership

    def get_team_membership(self, team_id: int, user_id: int) -> Optional[Any]:
        """Get user's membership in a team."""
        TeamMember = self._get_team_member_model()
        return TeamMember.query.filter_by(
            team_id=team_id,
            user_id=user_id
        ).first()

    def get_team_members(self, team_id: int) -> List[Any]:
        """Get all members of a team."""
        TeamMember = self._get_team_member_model()
        return TeamMember.query.filter_by(team_id=team_id).all()

    def add_team_member(self, team_id: int, user_id: int, role: str = 'member') -> Any:
        """Add a member to a team."""
        TeamMember = self._get_team_member_model()
        db = self._get_db()

        existing = self.get_team_membership(team_id, user_id)
        if existing:
            return existing

        member = TeamMember(
            team_id=team_id,
            user_id=user_id,
            role=role
        )
        db.session.add(member)
        db.session.commit()

        logger.info(f"Added user {user_id} to team {team_id}")
        return member

    def remove_team_member(self, team_id: int, user_id: int) -> bool:
        """Remove a member from a team."""
        db = self._get_db()
        member = self.get_team_membership(team_id, user_id)
        if member:
            db.session.delete(member)
            db.session.commit()
            logger.info(f"Removed user {user_id} from team {team_id}")
            return True
        return False

    def get_user_teams(self, user_id: int, org_id: int = None) -> List[Any]:
        """Get all teams for a user, optionally filtered by organization."""
        TeamMember = self._get_team_member_model()
        query = TeamMember.query.filter_by(user_id=user_id)

        memberships = query.all()
        teams = [m.team for m in memberships if m.team]

        if org_id:
            teams = [t for t in teams if t.organization_id == org_id]

        return teams

    # SSO Management

    def configure_sso(self, org_id: int, provider: str, config: Dict) -> bool:
        """Configure SSO for an organization."""
        db = self._get_db()
        org = self.get_organization(org_id)
        if not org:
            return False

        org.sso_enabled = True
        org.sso_provider = provider
        org.sso_config = config
        db.session.commit()

        logger.info(f"Configured SSO for org {org_id}: {provider}")
        return True

    def disable_sso(self, org_id: int) -> bool:
        """Disable SSO for an organization."""
        db = self._get_db()
        org = self.get_organization(org_id)
        if not org:
            return False

        org.sso_enabled = False
        org.sso_provider = None
        org.sso_config = None
        db.session.commit()

        logger.info(f"Disabled SSO for org {org_id}")
        return True

    def get_sso_config(self, org_id: int) -> Optional[Dict]:
        """Get SSO configuration for an organization."""
        org = self.get_organization(org_id)
        if org and org.sso_enabled:
            return {
                'provider': org.sso_provider,
                'config': org.sso_config,
                'enabled': True
            }
        return None

    # Helper Methods

    def user_has_org_permission(self, org_id: int, user_id: int,
                                 required_roles: List[str]) -> bool:
        """Check if user has required role in organization."""
        member = self.get_membership(org_id, user_id)
        if not member:
            return False
        return member.role in required_roles

    def is_org_admin(self, org_id: int, user_id: int) -> bool:
        """Check if user is an admin or owner of the organization."""
        return self.user_has_org_permission(org_id, user_id, ['owner', 'admin'])

    def is_org_owner(self, org_id: int, user_id: int) -> bool:
        """Check if user is the owner of the organization."""
        return self.user_has_org_permission(org_id, user_id, ['owner'])

    def get_org_stats(self, org_id: int) -> Dict:
        """Get statistics for an organization."""
        members = self.get_organization_members(org_id)
        teams = self.get_organization_teams(org_id)

        return {
            'total_members': len(members),
            'total_teams': len(teams),
            'members_by_role': {
                role: len([m for m in members if m.role == role])
                for role in ['owner', 'admin', 'member', 'billing', 'viewer']
            }
        }


# Factory function
def get_multi_tenancy_service(user_id: Optional[int] = None) -> MultiTenancyService:
    """Get multi-tenancy service instance."""
    return MultiTenancyService(user_id)
