---
name: flask-test
description: Comprehensive testing workflow for the DevOps Agent Flask application. Use when testing the Flask app, checking endpoints, running test suites, or validating functionality.
---

# Flask Application Testing Guide

## Overview

This skill guides you through comprehensive testing of the DevOps Agent Flask application, including unit tests, integration tests, endpoint validation, and database testing.

## Testing Workflow

### Phase 1: Environment Setup

1. **Verify Virtual Environment**
   - Ensure the virtual environment is activated
   - Check: `which python` should point to `venv/bin/python` or `venv/Scripts/python`

2. **Install Test Dependencies**
   - If pytest not installed: `pip install pytest pytest-cov pytest-flask`
   - Verify: `pytest --version`

3. **Check Test Configuration**
   - Review `tests/` directory structure
   - Ensure test database configuration in `.env` or use SQLite in-memory

### Phase 2: Run Test Suites

#### Unit Tests
```bash
# Run all unit tests
pytest tests/ -v

# Run specific test file
pytest tests/test_agent.py -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

#### Integration Tests
```bash
# Run integration tests
pytest tests/test_integration.py -v

# Run Stripe integration tests (requires test keys)
pytest tests/test_stripe.py -v
```

#### Database Tests
```bash
# Test database models and queries
pytest tests/test_db.py -v

# Test migrations
python test_db.py
```

### Phase 3: Manual Endpoint Testing

#### Authentication Endpoints
- `POST /login` - Test login with valid/invalid credentials
- `POST /signup` - Test user registration
- `POST /logout` - Test logout functionality

#### API Endpoints
- `POST /chat` - Test chat functionality with Claude
- `GET /api/conversations` - List conversations
- `GET /api/messages/<conversation_id>` - Get messages
- `POST /api/aws/*` - Test AWS integration endpoints
- `POST /api/kubernetes/*` - Test K8s endpoints

#### Subscription Endpoints
- `GET /pricing` - Test pricing page
- `POST /create-checkout-session` - Test Stripe checkout
- `GET /subscription` - Test subscription status

### Phase 4: Test Checklist

**Authentication & Authorization:**
- [ ] User can sign up with valid email
- [ ] User can log in with correct credentials
- [ ] Login fails with incorrect password
- [ ] Protected routes require authentication
- [ ] CSRF protection works on forms

**Chat Functionality:**
- [ ] User can send messages to Claude
- [ ] Conversations are saved to database
- [ ] Messages are associated with correct conversation
- [ ] Auto-naming works for new conversations
- [ ] Recent chats display correctly

**Subscription System:**
- [ ] Free tier has correct limits
- [ ] Premium tier features are locked for free users
- [ ] Stripe checkout creates session correctly
- [ ] Webhooks update subscription status
- [ ] Credit system tracks usage

**Security:**
- [ ] Rate limiting works on login endpoint
- [ ] XSS protection (test with `<script>alert('xss')</script>`)
- [ ] SQL injection protection (test with `' OR 1=1--`)
- [ ] CSRF tokens are validated
- [ ] Session management is secure

**Cloud Integrations:**
- [ ] AWS tools work with valid credentials
- [ ] GCP tools work with service account
- [ ] Kubernetes tools connect to cluster
- [ ] Error handling for invalid credentials

### Phase 5: Performance Testing

```python
# Test response times
import time
start = time.time()
# Make request
response = client.post('/chat', json={...})
duration = time.time() - start
assert duration < 5.0  # Should respond within 5 seconds
```

### Phase 6: Test Reporting

1. **Generate Coverage Report**
   ```bash
   pytest --cov=src --cov-report=html --cov-report=term
   ```

2. **Review Coverage**
   - Open `htmlcov/index.html` in browser
   - Aim for >80% coverage

3. **Document Results**
   - Note any failing tests
   - Document bugs found
   - Track performance metrics

## Common Test Patterns

### Testing Flask Routes
```python
def test_login_route(client):
    response = client.post('/login', data={
        'email': 'test@example.com',
        'password': 'password123'
    })
    assert response.status_code == 200
```

### Testing Database Operations
```python
def test_create_user(db_session):
    user = User(email='test@example.com')
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    assert User.query.filter_by(email='test@example.com').first() is not None
```

### Testing Claude Integration
```python
def test_chat_with_claude(client, authenticated_user):
    response = client.post('/chat', json={
        'message': 'Hello, test message',
        'conversation_id': 1
    })
    data = response.get_json()
    assert 'response' in data
    assert data['response'] != ''
```

## Troubleshooting

**Tests fail with "Database not found":**
- Create test database: `python -c "from models import db; db.create_all()"`
- Or use SQLite in-memory: Set `SQLALCHEMY_DATABASE_URI` to `sqlite:///:memory:`

**Import errors:**
- Activate virtual environment
- Install dependencies: `pip install -r requirements.txt`
- Check Python path includes project root

**Stripe tests fail:**
- Set test keys in `.env`: `STRIPE_SECRET_KEY=sk_test_...`
- Use Stripe test mode
- Check webhook endpoint

## Best Practices

1. **Always test in development first** - Never test destructive operations in production
2. **Use fixtures** - Create reusable test data with pytest fixtures
3. **Mock external services** - Mock AWS, GCP, Stripe in unit tests
4. **Test edge cases** - Empty inputs, invalid data, boundary conditions
5. **Keep tests fast** - Use in-memory database for unit tests
6. **Clean up after tests** - Reset database state between tests

## Quick Commands

```bash
# Run all tests
pytest

# Run tests with output
pytest -v

# Run specific test
pytest tests/test_agent.py::test_chat_functionality

# Run tests matching pattern
pytest -k "test_auth"

# Show test coverage
pytest --cov=src

# Run tests in parallel (requires pytest-xdist)
pytest -n auto

# Run only failed tests from last run
pytest --lf

# Generate HTML test report
pytest --html=report.html
```
