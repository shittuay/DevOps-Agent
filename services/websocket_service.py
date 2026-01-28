"""
WebSocket Service for DevOps Agent

Provides real-time communication for:
- Task progress updates
- Cloud operation status
- Notifications and alerts
- Live log streaming
"""

import logging
from functools import wraps
from typing import Optional, Dict, Any
from flask import request
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect

logger = logging.getLogger(__name__)

# Initialize SocketIO with eventlet/gevent async mode
socketio = SocketIO(
    cors_allowed_origins="*",
    async_mode='threading',  # Use 'eventlet' or 'gevent' in production
    ping_timeout=60,
    ping_interval=25
)


def init_socketio(app):
    """Initialize SocketIO with Flask app."""
    socketio.init_app(app)
    register_handlers()
    logger.info("WebSocket service initialized")
    return socketio


def authenticated_only(f):
    """Decorator to require authentication for socket events."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        from flask_login import current_user
        if not current_user.is_authenticated:
            disconnect()
            return
        return f(*args, **kwargs)
    return wrapped


def register_handlers():
    """Register all WebSocket event handlers."""

    @socketio.on('connect')
    def handle_connect():
        """Handle client connection."""
        from flask_login import current_user

        if current_user.is_authenticated:
            # Join user-specific room
            user_room = f"user_{current_user.id}"
            join_room(user_room)
            logger.info(f"User {current_user.id} connected to WebSocket")

            emit('connected', {
                'status': 'connected',
                'user_id': current_user.id,
                'room': user_room
            })
        else:
            # Allow anonymous connections for public pages
            emit('connected', {'status': 'connected', 'authenticated': False})

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection."""
        from flask_login import current_user

        if current_user.is_authenticated:
            user_room = f"user_{current_user.id}"
            leave_room(user_room)
            logger.info(f"User {current_user.id} disconnected from WebSocket")

    @socketio.on('join_room')
    @authenticated_only
    def handle_join_room(data):
        """Join a specific room for targeted updates."""
        room = data.get('room')
        if room:
            join_room(room)
            emit('room_joined', {'room': room})
            logger.debug(f"Joined room: {room}")

    @socketio.on('leave_room')
    @authenticated_only
    def handle_leave_room(data):
        """Leave a specific room."""
        room = data.get('room')
        if room:
            leave_room(room)
            emit('room_left', {'room': room})
            logger.debug(f"Left room: {room}")

    @socketio.on('subscribe_task')
    @authenticated_only
    def handle_subscribe_task(data):
        """Subscribe to task progress updates."""
        task_id = data.get('task_id')
        if task_id:
            room = f"task_{task_id}"
            join_room(room)
            emit('subscribed', {'task_id': task_id, 'room': room})

    @socketio.on('unsubscribe_task')
    @authenticated_only
    def handle_unsubscribe_task(data):
        """Unsubscribe from task progress updates."""
        task_id = data.get('task_id')
        if task_id:
            room = f"task_{task_id}"
            leave_room(room)
            emit('unsubscribed', {'task_id': task_id})

    @socketio.on('ping')
    def handle_ping():
        """Handle ping for connection keep-alive."""
        emit('pong', {'timestamp': __import__('time').time()})


# ==========================================
# Emit Functions (for use from other modules)
# ==========================================

def emit_to_user(user_id: int, event: str, data: Dict[str, Any]):
    """
    Emit an event to a specific user.

    Args:
        user_id: Target user ID
        event: Event name
        data: Event data
    """
    room = f"user_{user_id}"
    socketio.emit(event, data, room=room)
    logger.debug(f"Emitted {event} to user {user_id}")


def emit_task_progress(task_id: str, progress: int, status: str,
                       message: str = None, data: Dict[str, Any] = None):
    """
    Emit task progress update.

    Args:
        task_id: Task identifier
        progress: Progress percentage (0-100)
        status: Task status (pending, running, completed, failed)
        message: Optional status message
        data: Optional additional data
    """
    room = f"task_{task_id}"
    payload = {
        'task_id': task_id,
        'progress': progress,
        'status': status,
        'message': message,
        'data': data or {}
    }
    socketio.emit('task_progress', payload, room=room)
    logger.debug(f"Task {task_id} progress: {progress}% - {status}")


def emit_notification(user_id: int, notification_type: str, title: str,
                      message: str, data: Dict[str, Any] = None):
    """
    Send notification to user.

    Args:
        user_id: Target user ID
        notification_type: Type (info, success, warning, error)
        title: Notification title
        message: Notification message
        data: Optional additional data
    """
    emit_to_user(user_id, 'notification', {
        'type': notification_type,
        'title': title,
        'message': message,
        'data': data or {},
        'timestamp': __import__('time').time()
    })


def emit_cloud_update(user_id: int, provider: str, resource_type: str,
                      action: str, resource: Dict[str, Any]):
    """
    Emit cloud resource update.

    Args:
        user_id: Target user ID
        provider: Cloud provider (aws, gcp, azure)
        resource_type: Resource type (instance, bucket, etc.)
        action: Action performed (created, updated, deleted)
        resource: Resource data
    """
    emit_to_user(user_id, 'cloud_update', {
        'provider': provider,
        'resource_type': resource_type,
        'action': action,
        'resource': resource,
        'timestamp': __import__('time').time()
    })


def emit_chat_response(user_id: int, conversation_id: int, chunk: str,
                       is_final: bool = False):
    """
    Stream chat response chunks to user.

    Args:
        user_id: Target user ID
        conversation_id: Conversation ID
        chunk: Response text chunk
        is_final: Whether this is the final chunk
    """
    emit_to_user(user_id, 'chat_response', {
        'conversation_id': conversation_id,
        'chunk': chunk,
        'is_final': is_final,
        'timestamp': __import__('time').time()
    })


def emit_log_entry(user_id: int, log_type: str, level: str, message: str,
                   source: str = None):
    """
    Stream log entries to user.

    Args:
        user_id: Target user ID
        log_type: Log category (deployment, security, audit)
        level: Log level (debug, info, warning, error)
        message: Log message
        source: Log source identifier
    """
    emit_to_user(user_id, 'log_entry', {
        'type': log_type,
        'level': level,
        'message': message,
        'source': source,
        'timestamp': __import__('time').time()
    })


def emit_alert(user_id: int, alert_type: str, severity: str, title: str,
               message: str, actions: list = None):
    """
    Send alert to user.

    Args:
        user_id: Target user ID
        alert_type: Alert category
        severity: Severity level (low, medium, high, critical)
        title: Alert title
        message: Alert message
        actions: Optional list of action buttons
    """
    emit_to_user(user_id, 'alert', {
        'type': alert_type,
        'severity': severity,
        'title': title,
        'message': message,
        'actions': actions or [],
        'timestamp': __import__('time').time()
    })


def broadcast_system_message(message: str, message_type: str = 'info'):
    """
    Broadcast system message to all connected users.

    Args:
        message: Message content
        message_type: Message type (info, warning, maintenance)
    """
    socketio.emit('system_message', {
        'type': message_type,
        'message': message,
        'timestamp': __import__('time').time()
    })
    logger.info(f"Broadcast system message: {message}")


# ==========================================
# Client-side JavaScript helper
# ==========================================

CLIENT_JS = """
// DevOps Agent WebSocket Client

class DevOpsSocket {
    constructor(options = {}) {
        this.socket = null;
        this.connected = false;
        this.handlers = {};
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = options.maxReconnectAttempts || 5;
        this.reconnectDelay = options.reconnectDelay || 1000;
    }

    connect() {
        this.socket = io({
            transports: ['websocket', 'polling'],
            upgrade: true,
            rememberUpgrade: true
        });

        this.socket.on('connect', () => {
            console.log('WebSocket connected');
            this.connected = true;
            this.reconnectAttempts = 0;
            this.trigger('connected');
        });

        this.socket.on('disconnect', (reason) => {
            console.log('WebSocket disconnected:', reason);
            this.connected = false;
            this.trigger('disconnected', reason);
        });

        this.socket.on('connect_error', (error) => {
            console.error('WebSocket error:', error);
            this.handleReconnect();
        });

        // Register default event handlers
        this.registerDefaultHandlers();
    }

    registerDefaultHandlers() {
        this.socket.on('notification', (data) => {
            this.trigger('notification', data);
            this.showNotification(data);
        });

        this.socket.on('task_progress', (data) => {
            this.trigger('task_progress', data);
        });

        this.socket.on('chat_response', (data) => {
            this.trigger('chat_response', data);
        });

        this.socket.on('cloud_update', (data) => {
            this.trigger('cloud_update', data);
        });

        this.socket.on('alert', (data) => {
            this.trigger('alert', data);
            this.showAlert(data);
        });

        this.socket.on('system_message', (data) => {
            this.trigger('system_message', data);
        });
    }

    handleReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            const delay = this.reconnectDelay * this.reconnectAttempts;
            console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
            setTimeout(() => this.socket.connect(), delay);
        }
    }

    on(event, callback) {
        if (!this.handlers[event]) {
            this.handlers[event] = [];
        }
        this.handlers[event].push(callback);
    }

    trigger(event, data) {
        if (this.handlers[event]) {
            this.handlers[event].forEach(callback => callback(data));
        }
    }

    subscribeToTask(taskId) {
        this.socket.emit('subscribe_task', { task_id: taskId });
    }

    unsubscribeFromTask(taskId) {
        this.socket.emit('unsubscribe_task', { task_id: taskId });
    }

    joinRoom(room) {
        this.socket.emit('join_room', { room: room });
    }

    leaveRoom(room) {
        this.socket.emit('leave_room', { room: room });
    }

    showNotification(data) {
        // Override this method to customize notification display
        if (window.Notification && Notification.permission === 'granted') {
            new Notification(data.title, { body: data.message });
        }
    }

    showAlert(data) {
        // Override this method to customize alert display
        console.warn(`Alert [${data.severity}]: ${data.title} - ${data.message}`);
    }

    disconnect() {
        if (this.socket) {
            this.socket.disconnect();
        }
    }
}

// Initialize global instance
window.devopsSocket = new DevOpsSocket();
"""


def get_client_js():
    """Return the client-side JavaScript code."""
    return CLIENT_JS
