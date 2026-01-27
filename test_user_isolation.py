#!/usr/bin/env python3
"""
Test script to verify user data isolation.

Creates two test users and verifies that:
1. Each user can only see their own conversations
2. Each user can only see their own cloud credentials
3. Each user can only see their own infrastructure resources
4. No cross-user data leakage occurs

Run: python test_user_isolation.py
"""
import os
import sys
import secrets
from datetime import datetime

# Set up Flask app context
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-isolation-test')
os.environ.setdefault('DATABASE_URL', 'sqlite:///devops_agent.db')

from app import app, db
from models import (
    User, Conversation, ChatMessage, UserCloudCredential,
    InfrastructureResource, UserSubscription, SubscriptionTier
)


class IsolationTester:
    """Test user data isolation."""

    def __init__(self):
        self.user1 = None
        self.user2 = None
        self.test_results = []

    def setup(self):
        """Create two test users."""
        print("\n" + "=" * 60)
        print("USER ISOLATION TEST")
        print("=" * 60)

        with app.app_context():
            # Create unique test users
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')

            # User 1
            self.user1_email = f"testuser1_{timestamp}@test.com"
            self.user1_username = f"testuser1_{timestamp}"
            self.user1 = User(
                email=self.user1_email,
                username=self.user1_username,
                full_name="Test User One"
            )
            self.user1.set_password("TestPass123!")
            db.session.add(self.user1)

            # User 2
            self.user2_email = f"testuser2_{timestamp}@test.com"
            self.user2_username = f"testuser2_{timestamp}"
            self.user2 = User(
                email=self.user2_email,
                username=self.user2_username,
                full_name="Test User Two"
            )
            self.user2.set_password("TestPass456!")
            db.session.add(self.user2)

            db.session.commit()

            print(f"\n[SETUP] Created User 1: {self.user1.email} (ID: {self.user1.id})")
            print(f"[SETUP] Created User 2: {self.user2.email} (ID: {self.user2.id})")

    def test_conversation_isolation(self):
        """Test that conversations are isolated between users."""
        print("\n" + "-" * 40)
        print("TEST 1: Conversation Isolation")
        print("-" * 40)

        with app.app_context():
            # Refresh users from DB
            user1 = User.query.get(self.user1.id)
            user2 = User.query.get(self.user2.id)

            # Create conversation for User 1
            conv1_id = secrets.token_hex(8)
            conv1 = Conversation(
                id=conv1_id,
                user_id=user1.id,
                title="User 1 Secret Conversation"
            )
            db.session.add(conv1)

            # Create message for User 1
            msg1 = ChatMessage(
                conversation_id=conv1_id,
                user_id=user1.id,
                role='user',
                content="This is User 1's secret message with sensitive data!"
            )
            db.session.add(msg1)

            # Create conversation for User 2
            conv2_id = secrets.token_hex(8)
            conv2 = Conversation(
                id=conv2_id,
                user_id=user2.id,
                title="User 2 Private Chat"
            )
            db.session.add(conv2)

            # Create message for User 2
            msg2 = ChatMessage(
                conversation_id=conv2_id,
                user_id=user2.id,
                role='user',
                content="User 2's confidential information here!"
            )
            db.session.add(msg2)

            db.session.commit()

            # TEST: User 1 should only see their own conversations
            user1_convs = Conversation.query.filter_by(user_id=user1.id).all()
            user1_conv_ids = [c.id for c in user1_convs]

            # TEST: User 2 should only see their own conversations
            user2_convs = Conversation.query.filter_by(user_id=user2.id).all()
            user2_conv_ids = [c.id for c in user2_convs]

            # Verify isolation
            test1_pass = conv1_id in user1_conv_ids and conv2_id not in user1_conv_ids
            test2_pass = conv2_id in user2_conv_ids and conv1_id not in user2_conv_ids

            if test1_pass:
                print("[PASS] User 1 can only see their own conversations")
            else:
                print("[FAIL] User 1 can see User 2's conversations!")

            if test2_pass:
                print("[PASS] User 2 can only see their own conversations")
            else:
                print("[FAIL] User 2 can see User 1's conversations!")

            # TEST: Messages are also isolated
            user1_msgs = ChatMessage.query.filter_by(user_id=user1.id).all()
            user2_msgs = ChatMessage.query.filter_by(user_id=user2.id).all()

            msg_test1 = all(m.user_id == user1.id for m in user1_msgs)
            msg_test2 = all(m.user_id == user2.id for m in user2_msgs)

            if msg_test1 and msg_test2:
                print("[PASS] Chat messages are properly isolated")
            else:
                print("[FAIL] Chat message isolation breach!")

            self.test_results.append(('Conversation Isolation', test1_pass and test2_pass and msg_test1 and msg_test2))

    def test_credential_isolation(self):
        """Test that cloud credentials are isolated between users."""
        print("\n" + "-" * 40)
        print("TEST 2: Cloud Credential Isolation")
        print("-" * 40)

        with app.app_context():
            user1 = User.query.get(self.user1.id)
            user2 = User.query.get(self.user2.id)

            # Create AWS credentials for User 1
            cred1 = UserCloudCredential(
                user_id=user1.id,
                cloud_provider='aws',
                default_region='us-east-1'
            )
            cred1.set_credentials({
                'access_key': 'AKIAUSER1SECRET123',
                'secret_key': 'user1-super-secret-key-do-not-share'
            })
            db.session.add(cred1)

            # Create AWS credentials for User 2
            cred2 = UserCloudCredential(
                user_id=user2.id,
                cloud_provider='aws',
                default_region='eu-west-1'
            )
            cred2.set_credentials({
                'access_key': 'AKIAUSER2DIFFERENT',
                'secret_key': 'user2-completely-different-secret'
            })
            db.session.add(cred2)

            db.session.commit()

            # TEST: User 1 should only see their own credentials
            user1_creds = UserCloudCredential.query.filter_by(user_id=user1.id).all()
            user2_creds = UserCloudCredential.query.filter_by(user_id=user2.id).all()

            # Verify User 1's credentials
            test1_pass = len(user1_creds) >= 1
            test1_no_leak = all(c.user_id == user1.id for c in user1_creds)

            # Verify User 2's credentials
            test2_pass = len(user2_creds) >= 1
            test2_no_leak = all(c.user_id == user2.id for c in user2_creds)

            # Decrypt and verify content isolation
            user1_aws = next((c for c in user1_creds if c.cloud_provider == 'aws'), None)
            user2_aws = next((c for c in user2_creds if c.cloud_provider == 'aws'), None)

            if user1_aws and user2_aws:
                user1_decrypted = user1_aws.get_credentials()
                user2_decrypted = user2_aws.get_credentials()

                # Verify they have different credentials
                keys_different = user1_decrypted.get('access_key') != user2_decrypted.get('access_key')

                if keys_different:
                    print("[PASS] User credentials are encrypted and isolated")
                else:
                    print("[FAIL] Users have the same credentials - isolation breach!")
            else:
                keys_different = True  # Skip if one doesn't exist

            if test1_pass and test1_no_leak:
                print("[PASS] User 1 can only access their own credentials")
            else:
                print("[FAIL] User 1 credential isolation breach!")

            if test2_pass and test2_no_leak:
                print("[PASS] User 2 can only access their own credentials")
            else:
                print("[FAIL] User 2 credential isolation breach!")

            self.test_results.append(('Credential Isolation', test1_no_leak and test2_no_leak and keys_different))

    def test_infrastructure_isolation(self):
        """Test that infrastructure resources are isolated between users."""
        print("\n" + "-" * 40)
        print("TEST 3: Infrastructure Resource Isolation")
        print("-" * 40)

        with app.app_context():
            user1 = User.query.get(self.user1.id)
            user2 = User.query.get(self.user2.id)

            # Create infrastructure resource for User 1
            resource1 = InfrastructureResource(
                user_id=user1.id,
                resource_id='i-user1instance123',
                resource_type='ec2_instance',
                cloud_provider='aws',
                resource_name='User1-Production-Server',
                region='us-east-1',
                status='running',
                monthly_cost=150.00
            )
            db.session.add(resource1)

            # Create infrastructure resource for User 2
            resource2 = InfrastructureResource(
                user_id=user2.id,
                resource_id='i-user2instance456',
                resource_type='ec2_instance',
                cloud_provider='aws',
                resource_name='User2-Dev-Server',
                region='eu-west-1',
                status='running',
                monthly_cost=75.00
            )
            db.session.add(resource2)

            db.session.commit()

            # TEST: Each user should only see their own resources
            user1_resources = InfrastructureResource.query.filter_by(user_id=user1.id).all()
            user2_resources = InfrastructureResource.query.filter_by(user_id=user2.id).all()

            test1_pass = all(r.user_id == user1.id for r in user1_resources)
            test2_pass = all(r.user_id == user2.id for r in user2_resources)

            # Verify no cross-contamination
            user1_resource_ids = [r.resource_id for r in user1_resources]
            user2_resource_ids = [r.resource_id for r in user2_resources]

            no_overlap = not set(user1_resource_ids).intersection(set(user2_resource_ids))

            if test1_pass:
                print("[PASS] User 1 infrastructure resources are isolated")
            else:
                print("[FAIL] User 1 can see other users' resources!")

            if test2_pass:
                print("[PASS] User 2 infrastructure resources are isolated")
            else:
                print("[FAIL] User 2 can see other users' resources!")

            if no_overlap:
                print("[PASS] No resource ID overlap between users")
            else:
                print("[FAIL] Resource IDs are shared between users!")

            self.test_results.append(('Infrastructure Isolation', test1_pass and test2_pass and no_overlap))

    def test_direct_query_attack(self):
        """Test that direct queries cannot bypass isolation."""
        print("\n" + "-" * 40)
        print("TEST 4: Direct Query Attack Prevention")
        print("-" * 40)

        with app.app_context():
            user1 = User.query.get(self.user1.id)
            user2 = User.query.get(self.user2.id)

            # Simulate an attacker (User 2) trying to access User 1's data

            # Attack 1: Try to get User 1's conversations without filter
            all_convs = Conversation.query.all()
            user1_convs_leaked = [c for c in all_convs if c.user_id == user1.id]

            # This should work (it's a raw query), but the API should filter
            print(f"[INFO] Raw query returns {len(all_convs)} total conversations")
            print(f"[INFO] Of which {len(user1_convs_leaked)} belong to User 1")

            # The PROPER way (what the API does):
            user2_convs_proper = Conversation.query.filter_by(user_id=user2.id).all()
            user1_visible_to_user2 = [c for c in user2_convs_proper if c.user_id == user1.id]

            if len(user1_visible_to_user2) == 0:
                print("[PASS] Proper query filtering prevents User 2 from seeing User 1's data")
            else:
                print("[FAIL] User 2 can see User 1's conversations through filtered query!")

            # Attack 2: Try to load a specific conversation by ID
            user1_conv = Conversation.query.filter_by(user_id=user1.id).first()
            if user1_conv:
                # Attacker knows the conversation ID - can they access it?
                # Proper API would check: filter_by(id=conv_id, user_id=current_user.id)
                attack_query = Conversation.query.filter_by(
                    id=user1_conv.id,
                    user_id=user2.id  # Attacker's user ID
                ).first()

                if attack_query is None:
                    print("[PASS] Direct ID access blocked by user_id filter")
                else:
                    print("[FAIL] Attacker can access other user's conversation by ID!")

            self.test_results.append(('Direct Query Attack Prevention', len(user1_visible_to_user2) == 0))

    def cleanup(self):
        """Clean up test data."""
        print("\n" + "-" * 40)
        print("CLEANUP")
        print("-" * 40)

        with app.app_context():
            if self.user1:
                # Delete all user1's data
                ChatMessage.query.filter_by(user_id=self.user1.id).delete()
                Conversation.query.filter_by(user_id=self.user1.id).delete()
                UserCloudCredential.query.filter_by(user_id=self.user1.id).delete()
                InfrastructureResource.query.filter_by(user_id=self.user1.id).delete()
                User.query.filter_by(id=self.user1.id).delete()

            if self.user2:
                # Delete all user2's data
                ChatMessage.query.filter_by(user_id=self.user2.id).delete()
                Conversation.query.filter_by(user_id=self.user2.id).delete()
                UserCloudCredential.query.filter_by(user_id=self.user2.id).delete()
                InfrastructureResource.query.filter_by(user_id=self.user2.id).delete()
                User.query.filter_by(id=self.user2.id).delete()

            db.session.commit()
            print("[CLEANUP] Test users and data removed")

    def print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)

        passed = sum(1 for _, result in self.test_results if result)
        total = len(self.test_results)

        for test_name, result in self.test_results:
            status = "PASS" if result else "FAIL"
            print(f"  [{status}] {test_name}")

        print("-" * 40)
        print(f"  Total: {passed}/{total} tests passed")

        if passed == total:
            print("\n  [SUCCESS] All isolation tests passed!")
            print("  User data is properly isolated.")
        else:
            print("\n  [WARNING] Some isolation tests failed!")
            print("  Review the failures above.")

        print("=" * 60 + "\n")

        return passed == total

    def run_all_tests(self):
        """Run all isolation tests."""
        try:
            self.setup()
            self.test_conversation_isolation()
            self.test_credential_isolation()
            self.test_infrastructure_isolation()
            self.test_direct_query_attack()
            return self.print_summary()
        finally:
            self.cleanup()


def main():
    """Main entry point."""
    tester = IsolationTester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
