"""Azure tools for DevOps Agent."""
import re
import threading
from typing import Dict, Any, List, Optional
from ..utils import get_logger

logger = get_logger(__name__)

# Thread-local storage for user context (mirrors aws_tools.py's pattern)
_user_context = threading.local()


def set_user_context(user_id: Optional[int] = None):
    """Set user context for Azure operations in this thread."""
    _user_context.user_id = user_id


def clear_user_context():
    """Clear user context from this thread."""
    _user_context.user_id = None


def _get_current_user_id() -> Optional[int]:
    """Get current user ID: thread-local context first, then Flask request context."""
    user_id = getattr(_user_context, 'user_id', None)
    if user_id is not None:
        return user_id
    try:
        from flask import g, has_request_context
        if has_request_context() and hasattr(g, 'current_user_id'):
            return g.current_user_id
    except ImportError:
        pass
    return None


def _get_azure_client(service_type: str, user_id: Optional[int] = None):
    """
    Get Azure client for specified service using per-user credentials ONLY.

    SECURITY: Never falls back to environment/default credentials.
    Each user MUST configure their own Azure credentials.

    Args:
        service_type: Type of Azure service (compute, storage, network, etc.)
        user_id: Optional user ID to get per-user credentials. Falls back to the
            Flask request context when omitted.

    Note:
        This used to accept a `credential` argument, but it was overwritten by
        the per-user lookup below before ever being read - so a caller-supplied
        credential was silently ignored. It is removed rather than honoured,
        because accepting an injected credential would defeat the "per-user
        credentials ONLY" guarantee above. No caller passed it.

    Returns:
        Azure client instance

    Raises:
        Exception: If user context is not set or credentials are not configured
    """
    try:
        # Try to get user_id from Flask context if not provided
        if user_id is None:
            user_id = _get_current_user_id()

        # SECURITY: User context is REQUIRED - no anonymous Azure access
        if user_id is None:
            logger.error("Azure operation attempted without user context")
            raise Exception(
                "Authentication required. Please log in to access Azure resources."
            )

        # Use per-user credentials ONLY - no fallback to shared credentials
        try:
            from services.credential_service import get_user_azure_credential
            credential, subscription_id, location = get_user_azure_credential(user_id)
            logger.info(f"Using per-user Azure credentials for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to get Azure credentials for user {user_id}: {str(e)}")
            # SECURITY: Do NOT fall back to environment/default credentials
            raise Exception(
                "Azure credentials not configured. Please add your Azure credentials in Settings > Cloud Credentials."
            )

        # Import and construct ONLY the requested service's client — mirrors the
        # fix already applied to gcp_tools.py's _get_gcp_client(). This used to
        # import all seven azure-mgmt-* SDKs up front and eagerly construct all
        # seven clients regardless of which service_type was requested, so one
        # broken/missing package or one failed client construction (of the six
        # that get discarded) took down every Azure tool, not just the one
        # actually in use.
        if service_type == 'compute':
            from azure.mgmt.compute import ComputeManagementClient
            return ComputeManagementClient(credential, subscription_id)
        if service_type == 'storage':
            from azure.mgmt.storage import StorageManagementClient
            return StorageManagementClient(credential, subscription_id)
        if service_type == 'network':
            from azure.mgmt.network import NetworkManagementClient
            return NetworkManagementClient(credential, subscription_id)
        if service_type == 'resource':
            from azure.mgmt.resource import ResourceManagementClient
            return ResourceManagementClient(credential, subscription_id)
        if service_type == 'monitor':
            from azure.mgmt.monitor import MonitorManagementClient
            return MonitorManagementClient(credential, subscription_id)
        if service_type == 'container':
            from azure.mgmt.containerinstance import ContainerInstanceManagementClient
            return ContainerInstanceManagementClient(credential, subscription_id)
        if service_type == 'sql':
            from azure.mgmt.sql import SqlManagementClient
            return SqlManagementClient(credential, subscription_id)

        raise Exception(
            f"Unknown Azure service type: {service_type!r} "
            "(expected one of: compute, storage, network, resource, monitor, container, sql)"
        )
    except ImportError as e:
        raise Exception(f"Azure SDK package for '{service_type}' not installed: {e}")
    except Exception as e:
        raise Exception(f"Failed to create Azure client: {str(e)}")


def _friendly_azure_error(e: Exception) -> str:
    """Translate common Azure ARM error codes into an actionable message.

    A valid, correctly-scoped service principal can still fail to create
    resources for reasons that have nothing to do with the credentials
    themselves (subscription-level config, quota, region availability).
    Azure's raw SDK exception text names the ARM error code but doesn't say
    what to do about it, so callers see e.g. "AuthorizationFailed" and
    reasonably (but wrongly) assume the credentials are misconfigured.
    """
    msg = str(e)

    if 'AuthorizationFailed' in msg:
        return (
            "Azure denied this operation (AuthorizationFailed): the configured service "
            "principal doesn't have sufficient RBAC permissions for this specific action. "
            "Regenerate the setup script in Settings > Cloud Credentials with 'Contributor' "
            "access level, or ask your Azure admin to grant Contributor on this subscription "
            f"(or resource group). Original error: {msg}"
        )

    provider_match = re.search(r"not registered to use namespace '([^']+)'", msg)
    if provider_match or 'MissingSubscriptionRegistration' in msg:
        namespace = provider_match.group(1) if provider_match else '<namespace>'
        return (
            f"This Azure subscription hasn't registered the {namespace} resource provider yet "
            "(MissingSubscriptionRegistration) — common on new or rarely-used subscriptions, "
            "and having Contributor access doesn't register it automatically. Run: "
            f"az provider register --namespace {namespace} --wait (one-time, takes a few minutes), "
            f"then retry. Original error: {msg}"
        )

    if 'QuotaExceeded' in msg or ('quota' in msg.lower() and 'OperationNotAllowed' in msg):
        return (
            "Azure quota exceeded for this subscription/region (QuotaExceeded). Request a quota "
            "increase in the Azure Portal (Subscriptions > Usage + quotas), or choose a smaller "
            f"size or a different region. Original error: {msg}"
        )

    if 'SkuNotAvailable' in msg:
        return (
            "The requested size/SKU isn't available in this region for this subscription "
            f"(SkuNotAvailable). Try a different VM size or a different region. Original error: {msg}"
        )

    return msg


def list_virtual_machines(resource_group: Optional[str] = None) -> Dict[str, Any]:
    """
    List Azure Virtual Machines.

    Args:
        resource_group: Optional resource group name to filter

    Returns:
        Dictionary with VM information
    """
    try:
        compute_client = _get_azure_client('compute')

        vms = []
        if resource_group:
            vm_list = compute_client.virtual_machines.list(resource_group)
        else:
            vm_list = compute_client.virtual_machines.list_all()

        for vm in vm_list:
            vms.append({
                'name': vm.name,
                'location': vm.location,
                'resource_group': vm.id.split('/')[4],
                'vm_size': vm.hardware_profile.vm_size,
                'provisioning_state': vm.provisioning_state,
                'os_type': vm.storage_profile.os_disk.os_type,
                'tags': vm.tags or {}
            })

        return {
            'success': True,
            'count': len(vms),
            'virtual_machines': vms
        }
    except Exception as e:
        logger.error(f"Error listing Azure VMs: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_vm_details(resource_group: str, vm_name: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific Azure VM.

    Args:
        resource_group: Resource group name
        vm_name: Virtual machine name

    Returns:
        Dictionary with VM details
    """
    try:
        compute_client = _get_azure_client('compute')

        vm = compute_client.virtual_machines.get(resource_group, vm_name, expand='instanceView')

        # Get instance view for status
        statuses = []
        if vm.instance_view and vm.instance_view.statuses:
            statuses = [{'code': s.code, 'display_status': s.display_status} for s in vm.instance_view.statuses]

        return {
            'success': True,
            'vm': {
                'name': vm.name,
                'id': vm.id,
                'location': vm.location,
                'vm_size': vm.hardware_profile.vm_size,
                'os_type': vm.storage_profile.os_disk.os_type,
                'os_disk_name': vm.storage_profile.os_disk.name,
                'network_interfaces': [nic.id for nic in vm.network_profile.network_interfaces] if vm.network_profile else [],
                'provisioning_state': vm.provisioning_state,
                'statuses': statuses,
                'tags': vm.tags or {}
            }
        }
    except Exception as e:
        logger.error(f"Error getting Azure VM details: {str(e)}")
        return {'success': False, 'error': str(e)}


def manage_vm(resource_group: str, vm_name: str, action: str) -> Dict[str, Any]:
    """
    Manage Azure VM (start, stop, restart, deallocate).

    Args:
        resource_group: Resource group name
        vm_name: Virtual machine name
        action: Action to perform (start, stop, restart, deallocate)

    Returns:
        Dictionary with operation result
    """
    try:
        compute_client = _get_azure_client('compute')

        if action == 'start':
            operation = compute_client.virtual_machines.begin_start(resource_group, vm_name)
        elif action == 'stop':
            operation = compute_client.virtual_machines.begin_power_off(resource_group, vm_name)
        elif action == 'restart':
            operation = compute_client.virtual_machines.begin_restart(resource_group, vm_name)
        elif action == 'deallocate':
            operation = compute_client.virtual_machines.begin_deallocate(resource_group, vm_name)
        else:
            return {'success': False, 'error': f'Invalid action: {action}'}

        # Wait for operation to complete
        operation.wait()

        return {
            'success': True,
            'message': f'VM {vm_name} {action} operation completed',
            'resource_group': resource_group,
            'vm_name': vm_name,
            'action': action
        }
    except Exception as e:
        logger.error(f"Error managing Azure VM: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


def list_storage_accounts(resource_group: Optional[str] = None) -> Dict[str, Any]:
    """
    List Azure Storage Accounts.

    Args:
        resource_group: Optional resource group name to filter

    Returns:
        Dictionary with storage account information
    """
    try:
        storage_client = _get_azure_client('storage')

        accounts = []
        if resource_group:
            account_list = storage_client.storage_accounts.list_by_resource_group(resource_group)
        else:
            account_list = storage_client.storage_accounts.list()

        for account in account_list:
            accounts.append({
                'name': account.name,
                'location': account.location,
                'resource_group': account.id.split('/')[4],
                'sku': account.sku.name,
                'kind': account.kind,
                'provisioning_state': account.provisioning_state,
                'primary_location': account.primary_location,
                'tags': account.tags or {}
            })

        return {
            'success': True,
            'count': len(accounts),
            'storage_accounts': accounts
        }
    except Exception as e:
        logger.error(f"Error listing Azure Storage Accounts: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_resource_groups() -> Dict[str, Any]:
    """
    List all Azure Resource Groups.

    Returns:
        Dictionary with resource group information
    """
    try:
        resource_client = _get_azure_client('resource')

        groups = []
        for group in resource_client.resource_groups.list():
            groups.append({
                'name': group.name,
                'location': group.location,
                'provisioning_state': group.properties.provisioning_state,
                'tags': group.tags or {}
            })

        return {
            'success': True,
            'count': len(groups),
            'resource_groups': groups
        }
    except Exception as e:
        logger.error(f"Error listing Azure Resource Groups: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_azure_metrics(
    resource_id: str,
    metric_names: List[str],
    timespan: Optional[str] = None,
    aggregation: str = 'Average',
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get Azure Monitor metrics for a resource using per-user credentials.

    Args:
        resource_id: Full Azure resource ID
        metric_names: List of metric names to retrieve
        timespan: ISO 8601 timespan (e.g., 'PT1H' for last hour)
        aggregation: Aggregation type (Average, Total, Minimum, Maximum)
        user_id: Optional user ID for credential lookup

    Returns:
        Dictionary with metrics data
    """
    try:
        from azure.monitor.query import MetricsQueryClient
        from datetime import datetime, timedelta

        # Get user_id from Flask context if not provided
        if user_id is None:
            user_id = _get_current_user_id()

        # SECURITY: Require user authentication
        if user_id is None:
            raise Exception("Authentication required. Please log in to access Azure metrics.")

        # Get per-user credentials
        try:
            from services.credential_service import get_user_azure_credential
            credential, subscription_id, location = get_user_azure_credential(user_id)
        except Exception as e:
            raise Exception("Azure credentials not configured. Please add your Azure credentials in Settings.")

        client = MetricsQueryClient(credential)

        # Default to last hour if not specified
        if not timespan:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=1)

        metrics_data = []
        for metric_name in metric_names:
            response = client.query_resource(
                resource_id,
                metric_names=[metric_name],
                timespan=(start_time, end_time) if not timespan else timespan,
                aggregations=[aggregation]
            )

            for metric in response.metrics:
                for time_series in metric.timeseries:
                    data_points = []
                    for data in time_series.data:
                        data_points.append({
                            'timestamp': data.timestamp.isoformat(),
                            'value': getattr(data, aggregation.lower(), None)
                        })

                    metrics_data.append({
                        'name': metric.name,
                        'unit': metric.unit,
                        'aggregation': aggregation,
                        'data_points': data_points
                    })

        return {
            'success': True,
            'resource_id': resource_id,
            'metrics': metrics_data
        }
    except Exception as e:
        logger.error(f"Error getting Azure metrics: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_container_instances(resource_group: Optional[str] = None) -> Dict[str, Any]:
    """
    List Azure Container Instances.

    Args:
        resource_group: Optional resource group name to filter

    Returns:
        Dictionary with container instance information
    """
    try:
        container_client = _get_azure_client('container')

        containers = []
        if resource_group:
            container_list = container_client.container_groups.list_by_resource_group(resource_group)
        else:
            container_list = container_client.container_groups.list()

        for container in container_list:
            containers.append({
                'name': container.name,
                'location': container.location,
                'resource_group': container.id.split('/')[4],
                'provisioning_state': container.provisioning_state,
                'os_type': container.os_type,
                'restart_policy': container.restart_policy,
                'ip_address': container.ip_address.ip if container.ip_address else None,
                'containers': [c.name for c in container.containers] if container.containers else [],
                'tags': container.tags or {}
            })

        return {
            'success': True,
            'count': len(containers),
            'container_instances': containers
        }
    except Exception as e:
        logger.error(f"Error listing Azure Container Instances: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_sql_servers(resource_group: Optional[str] = None) -> Dict[str, Any]:
    """
    List Azure SQL Servers.

    Args:
        resource_group: Optional resource group name to filter

    Returns:
        Dictionary with SQL server information
    """
    try:
        sql_client = _get_azure_client('sql')

        servers = []
        if resource_group:
            server_list = sql_client.servers.list_by_resource_group(resource_group)
        else:
            server_list = sql_client.servers.list()

        for server in server_list:
            servers.append({
                'name': server.name,
                'location': server.location,
                'resource_group': server.id.split('/')[4],
                'fully_qualified_domain_name': server.fully_qualified_domain_name,
                'version': server.version,
                'state': server.state,
                'administrator_login': server.administrator_login,
                'tags': server.tags or {}
            })

        return {
            'success': True,
            'count': len(servers),
            'sql_servers': servers
        }
    except Exception as e:
        logger.error(f"Error listing Azure SQL Servers: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_sql_databases(resource_group: str, server_name: str) -> Dict[str, Any]:
    """
    List databases on an Azure SQL Server.

    Args:
        resource_group: Resource group name
        server_name: SQL server name

    Returns:
        Dictionary with database information
    """
    try:
        sql_client = _get_azure_client('sql')

        databases = []
        for db in sql_client.databases.list_by_server(resource_group, server_name):
            databases.append({
                'name': db.name,
                'location': db.location,
                'status': db.status,
                'collation': db.collation,
                'max_size_bytes': db.max_size_bytes,
                'creation_date': db.creation_date.isoformat() if db.creation_date else None,
                'tags': db.tags or {}
            })

        return {
            'success': True,
            'server': server_name,
            'count': len(databases),
            'databases': databases
        }
    except Exception as e:
        logger.error(f"Error listing Azure SQL Databases: {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== CREATE OPERATIONS ====================


def create_resource_group(
    resource_group_name: str,
    location: str,
    tags: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Create a new Azure Resource Group.

    Args:
        resource_group_name: Name for the resource group
        location: Azure region (e.g., eastus, westus2, westeurope)
        tags: Optional tags as key-value pairs

    Returns:
        Dictionary with operation result
    """
    try:
        resource_client = _get_azure_client('resource')

        parameters = {'location': location}
        if tags:
            parameters['tags'] = tags

        result = resource_client.resource_groups.create_or_update(
            resource_group_name,
            parameters
        )

        return {
            'success': True,
            'resource_group_name': result.name,
            'location': result.location,
            'provisioning_state': result.properties.provisioning_state,
            'message': f'Successfully created resource group {result.name}'
        }
    except Exception as e:
        logger.error(f"Error creating Azure resource group: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


def create_virtual_machine(
    resource_group: str,
    vm_name: str,
    location: str,
    vm_size: str,
    admin_username: str,
    admin_password: str,
    image_publisher: str = 'Canonical',
    image_offer: str = 'UbuntuServer',
    image_sku: str = '18.04-LTS',
    os_disk_size_gb: int = 30,
    tags: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Create a new Azure Virtual Machine.

    Args:
        resource_group: Resource group name
        vm_name: Name for the virtual machine
        location: Azure region
        vm_size: VM size (e.g., Standard_B1s, Standard_D2s_v3)
        admin_username: Administrator username
        admin_password: Administrator password
        image_publisher: Image publisher (default: Canonical)
        image_offer: Image offer (default: UbuntuServer)
        image_sku: Image SKU (default: 18.04-LTS)
        os_disk_size_gb: OS disk size in GB (default: 30)
        tags: Optional tags

    Returns:
        Dictionary with operation result
    """
    try:
        from azure.mgmt.network.models import NetworkInterface, NetworkInterfaceIPConfiguration, Subnet, VirtualNetwork, PublicIPAddress
        from azure.mgmt.compute.models import VirtualMachine, HardwareProfile, StorageProfile, OSProfile, NetworkProfile, OSDisk, ImageReference, VirtualMachineSizeTypes

        compute_client = _get_azure_client('compute')
        network_client = _get_azure_client('network')

        # Create VNet
        vnet_name = f'{vm_name}-vnet'
        vnet_params = {
            'location': location,
            'address_space': {'address_prefixes': ['10.0.0.0/16']}
        }
        vnet_result = network_client.virtual_networks.begin_create_or_update(
            resource_group, vnet_name, vnet_params
        ).result()

        # Create Subnet
        subnet_name = f'{vm_name}-subnet'
        subnet_params = {'address_prefix': '10.0.0.0/24'}
        subnet_result = network_client.subnets.begin_create_or_update(
            resource_group, vnet_name, subnet_name, subnet_params
        ).result()

        # Create Public IP
        public_ip_name = f'{vm_name}-ip'
        public_ip_params = {
            'location': location,
            'public_ip_allocation_method': 'Dynamic'
        }
        public_ip_result = network_client.public_ip_addresses.begin_create_or_update(
            resource_group, public_ip_name, public_ip_params
        ).result()

        # Create NIC
        nic_name = f'{vm_name}-nic'
        nic_params = {
            'location': location,
            'ip_configurations': [{
                'name': 'ipconfig1',
                'subnet': {'id': subnet_result.id},
                'public_ip_address': {'id': public_ip_result.id}
            }]
        }
        nic_result = network_client.network_interfaces.begin_create_or_update(
            resource_group, nic_name, nic_params
        ).result()

        # Create VM
        vm_params = {
            'location': location,
            'hardware_profile': {'vm_size': vm_size},
            'storage_profile': {
                'image_reference': {
                    'publisher': image_publisher,
                    'offer': image_offer,
                    'sku': image_sku,
                    'version': 'latest'
                },
                'os_disk': {
                    'name': f'{vm_name}-osdisk',
                    'caching': 'ReadWrite',
                    'create_option': 'FromImage',
                    'disk_size_gb': os_disk_size_gb
                }
            },
            'os_profile': {
                'computer_name': vm_name,
                'admin_username': admin_username,
                'admin_password': admin_password
            },
            'network_profile': {
                'network_interfaces': [{'id': nic_result.id}]
            }
        }

        if tags:
            vm_params['tags'] = tags

        vm_result = compute_client.virtual_machines.begin_create_or_update(
            resource_group, vm_name, vm_params
        ).result()

        return {
            'success': True,
            'vm_name': vm_result.name,
            'location': vm_result.location,
            'vm_size': vm_result.hardware_profile.vm_size,
            'provisioning_state': vm_result.provisioning_state,
            'message': f'Successfully created VM {vm_result.name}. This process may take several minutes to complete.'
        }
    except Exception as e:
        logger.error(f"Error creating Azure VM: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


def create_storage_account(
    resource_group: str,
    storage_account_name: str,
    location: str,
    sku_name: str = 'Standard_LRS',
    kind: str = 'StorageV2',
    tags: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Create a new Azure Storage Account.

    Args:
        resource_group: Resource group name
        storage_account_name: Storage account name (must be globally unique, 3-24 lowercase alphanumeric chars)
        location: Azure region
        sku_name: SKU name (Standard_LRS, Standard_GRS, Standard_RAGRS, Premium_LRS)
        kind: Storage account kind (StorageV2, Storage, BlobStorage)
        tags: Optional tags

    Returns:
        Dictionary with operation result
    """
    try:
        from azure.mgmt.storage.models import StorageAccountCreateParameters, Sku

        storage_client = _get_azure_client('storage')

        params = StorageAccountCreateParameters(
            sku=Sku(name=sku_name),
            kind=kind,
            location=location,
            tags=tags or {}
        )

        result = storage_client.storage_accounts.begin_create(
            resource_group,
            storage_account_name,
            params
        ).result()

        return {
            'success': True,
            'storage_account_name': result.name,
            'location': result.location,
            'sku': result.sku.name,
            'kind': result.kind,
            'provisioning_state': result.provisioning_state,
            'primary_endpoints': {
                'blob': result.primary_endpoints.blob if result.primary_endpoints else None,
                'file': result.primary_endpoints.file if result.primary_endpoints else None,
                'queue': result.primary_endpoints.queue if result.primary_endpoints else None,
                'table': result.primary_endpoints.table if result.primary_endpoints else None
            },
            'message': f'Successfully created storage account {result.name}'
        }
    except Exception as e:
        logger.error(f"Error creating Azure storage account: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


def create_sql_server(
    resource_group: str,
    server_name: str,
    location: str,
    admin_username: str,
    admin_password: str,
    version: str = '12.0',
    tags: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Create a new Azure SQL Server.

    Args:
        resource_group: Resource group name
        server_name: SQL server name (must be globally unique)
        location: Azure region
        admin_username: Administrator username
        admin_password: Administrator password (must meet complexity requirements)
        version: SQL Server version (default: 12.0)
        tags: Optional tags

    Returns:
        Dictionary with operation result
    """
    try:
        from azure.mgmt.sql.models import Server

        sql_client = _get_azure_client('sql')

        server_params = Server(
            location=location,
            version=version,
            administrator_login=admin_username,
            administrator_login_password=admin_password,
            tags=tags or {}
        )

        result = sql_client.servers.begin_create_or_update(
            resource_group,
            server_name,
            server_params
        ).result()

        return {
            'success': True,
            'server_name': result.name,
            'location': result.location,
            'version': result.version,
            'fully_qualified_domain_name': result.fully_qualified_domain_name,
            'state': result.state,
            'message': f'Successfully created SQL Server {result.name}'
        }
    except Exception as e:
        logger.error(f"Error creating Azure SQL Server: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


def create_sql_database(
    resource_group: str,
    server_name: str,
    database_name: str,
    location: str,
    sku_name: str = 'Basic',
    sku_tier: str = 'Basic',
    max_size_bytes: int = 2147483648,  # 2GB
    tags: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Create a new Azure SQL Database on an existing SQL Server.

    Args:
        resource_group: Resource group name
        server_name: SQL server name
        database_name: Database name
        location: Azure region
        sku_name: SKU name (Basic, S0, S1, P1, etc.)
        sku_tier: SKU tier (Basic, Standard, Premium)
        max_size_bytes: Maximum database size in bytes (default: 2GB)
        tags: Optional tags

    Returns:
        Dictionary with operation result
    """
    try:
        from azure.mgmt.sql.models import Database, Sku

        sql_client = _get_azure_client('sql')

        db_params = Database(
            location=location,
            sku=Sku(name=sku_name, tier=sku_tier),
            max_size_bytes=max_size_bytes,
            tags=tags or {}
        )

        result = sql_client.databases.begin_create_or_update(
            resource_group,
            server_name,
            database_name,
            db_params
        ).result()

        return {
            'success': True,
            'database_name': result.name,
            'server_name': server_name,
            'location': result.location,
            'sku': f'{result.sku.name} ({result.sku.tier})',
            'status': result.status,
            'max_size_bytes': result.max_size_bytes,
            'message': f'Successfully created database {result.name} on server {server_name}'
        }
    except Exception as e:
        logger.error(f"Error creating Azure SQL Database: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


def delete_resource_group(
    resource_group_name: str,
    force: bool = False
) -> Dict[str, Any]:
    """
    Delete an Azure Resource Group and all its resources.

    WARNING: This will delete ALL resources in the resource group!

    Args:
        resource_group_name: Name of the resource group to delete
        force: If True, skip confirmation (use with caution)

    Returns:
        Dictionary with operation result
    """
    try:
        resource_client = _get_azure_client('resource')

        # Initiate deletion (this is async)
        result = resource_client.resource_groups.begin_delete(resource_group_name)

        return {
            'success': True,
            'resource_group_name': resource_group_name,
            'message': f'Successfully initiated deletion of resource group {resource_group_name}. This operation may take several minutes.',
            'warning': 'All resources in this resource group will be deleted!'
        }
    except Exception as e:
        logger.error(f"Error deleting Azure resource group: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


def delete_virtual_machine(
    resource_group: str,
    vm_name: str
) -> Dict[str, Any]:
    """
    Delete an Azure Virtual Machine.

    Args:
        resource_group: Resource group name
        vm_name: Virtual machine name

    Returns:
        Dictionary with operation result
    """
    try:
        compute_client = _get_azure_client('compute')

        result = compute_client.virtual_machines.begin_delete(resource_group, vm_name).result()

        return {
            'success': True,
            'vm_name': vm_name,
            'resource_group': resource_group,
            'message': f'Successfully deleted VM {vm_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting Azure VM: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}

# ==================== STORAGE LIFECYCLE ====================


def delete_storage_account(resource_group: str, storage_account_name: str) -> Dict[str, Any]:
    """Delete an Azure Storage Account."""
    try:
        storage_client = _get_azure_client('storage')
        storage_client.storage_accounts.delete(resource_group, storage_account_name)
        return {
            'success': True, 'storage_account_name': storage_account_name,
            'resource_group': resource_group,
            'message': f'Successfully deleted storage account {storage_account_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting Azure storage account: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


def list_storage_account_keys(resource_group: str, storage_account_name: str) -> Dict[str, Any]:
    """List access keys for a storage account."""
    try:
        storage_client = _get_azure_client('storage')
        keys = storage_client.storage_accounts.list_keys(resource_group, storage_account_name)
        return {
            'success': True, 'storage_account_name': storage_account_name,
            'keys': [{'key_name': k.key_name, 'value': k.value, 'permissions': k.permissions} for k in keys.keys],
            'message': f'Retrieved {len(keys.keys)} keys for {storage_account_name}'
        }
    except Exception as e:
        logger.error(f"Error listing storage account keys: {str(e)}")
        return {'success': False, 'error': str(e)}


def regenerate_storage_key(resource_group: str, storage_account_name: str, key_name: str = 'key1') -> Dict[str, Any]:
    """Regenerate a storage account access key."""
    try:
        storage_client = _get_azure_client('storage')
        keys = storage_client.storage_accounts.regenerate_key(
            resource_group, storage_account_name, {'key_name': key_name}
        )
        return {
            'success': True, 'storage_account_name': storage_account_name,
            'regenerated_key': key_name,
            'keys': [{'key_name': k.key_name, 'value': k.value} for k in keys.keys],
            'message': f'Successfully regenerated {key_name} for {storage_account_name}'
        }
    except Exception as e:
        logger.error(f"Error regenerating storage key: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


# ==================== NETWORK SECURITY GROUPS ====================


def list_network_security_groups(resource_group: Optional[str] = None) -> Dict[str, Any]:
    """List Azure Network Security Groups."""
    try:
        network_client = _get_azure_client('network')

        nsgs = []
        if resource_group:
            nsg_list = network_client.network_security_groups.list(resource_group)
        else:
            nsg_list = network_client.network_security_groups.list_all()

        for nsg in nsg_list:
            rules = []
            if nsg.security_rules:
                for rule in nsg.security_rules:
                    rules.append({
                        'name': rule.name,
                        'priority': rule.priority,
                        'direction': rule.direction,
                        'access': rule.access,
                        'protocol': rule.protocol,
                        'source': rule.source_address_prefix,
                        'destination': rule.destination_address_prefix,
                        'dest_port': rule.destination_port_range,
                    })

            nsgs.append({
                'name': nsg.name,
                'location': nsg.location,
                'resource_group': nsg.id.split('/')[4],
                'provisioning_state': nsg.provisioning_state,
                'rules_count': len(rules),
                'rules': rules,
                'tags': nsg.tags or {}
            })

        return {'success': True, 'count': len(nsgs), 'network_security_groups': nsgs}
    except Exception as e:
        logger.error(f"Error listing Azure NSGs: {str(e)}")
        return {'success': False, 'error': str(e)}


def create_network_security_group(
    resource_group: str,
    nsg_name: str,
    location: str,
    tags: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Create a Network Security Group."""
    try:
        network_client = _get_azure_client('network')
        params = {'location': location}
        if tags:
            params['tags'] = tags

        result = network_client.network_security_groups.begin_create_or_update(
            resource_group, nsg_name, params
        ).result()

        return {
            'success': True, 'nsg_name': result.name, 'location': result.location,
            'resource_group': resource_group,
            'provisioning_state': result.provisioning_state,
            'message': f'Successfully created NSG {result.name}'
        }
    except Exception as e:
        logger.error(f"Error creating Azure NSG: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


def create_nsg_rule(
    resource_group: str,
    nsg_name: str,
    rule_name: str,
    priority: int,
    direction: str = 'Inbound',
    access: str = 'Allow',
    protocol: str = 'Tcp',
    source_address: str = '*',
    source_port: str = '*',
    destination_address: str = '*',
    destination_port: str = '80'
) -> Dict[str, Any]:
    """Create a security rule in a Network Security Group."""
    try:
        network_client = _get_azure_client('network')
        rule_params = {
            'priority': priority,
            'direction': direction,
            'access': access,
            'protocol': protocol,
            'source_address_prefix': source_address,
            'source_port_range': source_port,
            'destination_address_prefix': destination_address,
            'destination_port_range': destination_port,
        }

        result = network_client.security_rules.begin_create_or_update(
            resource_group, nsg_name, rule_name, rule_params
        ).result()

        return {
            'success': True, 'rule_name': result.name, 'nsg_name': nsg_name,
            'priority': result.priority, 'direction': result.direction,
            'access': result.access, 'protocol': result.protocol,
            'destination_port': result.destination_port_range,
            'message': f'Successfully created rule {result.name} in NSG {nsg_name}'
        }
    except Exception as e:
        logger.error(f"Error creating NSG rule: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


def delete_network_security_group(resource_group: str, nsg_name: str) -> Dict[str, Any]:
    """Delete a Network Security Group."""
    try:
        network_client = _get_azure_client('network')
        network_client.network_security_groups.begin_delete(resource_group, nsg_name).result()
        return {
            'success': True, 'nsg_name': nsg_name, 'resource_group': resource_group,
            'message': f'Successfully deleted NSG {nsg_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting Azure NSG: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


# ==================== SQL LIFECYCLE ====================


def delete_sql_server(resource_group: str, server_name: str) -> Dict[str, Any]:
    """Delete an Azure SQL Server and all its databases."""
    try:
        sql_client = _get_azure_client('sql')
        sql_client.servers.begin_delete(resource_group, server_name).result()
        return {
            'success': True, 'server_name': server_name, 'resource_group': resource_group,
            'message': f'Successfully deleted SQL Server {server_name}',
            'warning': 'All databases on this server have been deleted.'
        }
    except Exception as e:
        logger.error(f"Error deleting Azure SQL Server: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


def delete_sql_database(resource_group: str, server_name: str, database_name: str) -> Dict[str, Any]:
    """Delete an Azure SQL Database."""
    try:
        sql_client = _get_azure_client('sql')
        sql_client.databases.begin_delete(resource_group, server_name, database_name).result()
        return {
            'success': True, 'database_name': database_name,
            'server_name': server_name, 'resource_group': resource_group,
            'message': f'Successfully deleted database {database_name} from server {server_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting Azure SQL Database: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


def create_sql_firewall_rule(
    resource_group: str,
    server_name: str,
    rule_name: str,
    start_ip: str,
    end_ip: str
) -> Dict[str, Any]:
    """Create a firewall rule on an Azure SQL Server."""
    try:
        sql_client = _get_azure_client('sql')
        result = sql_client.firewall_rules.create_or_update(
            resource_group, server_name, rule_name,
            {'start_ip_address': start_ip, 'end_ip_address': end_ip}
        )
        return {
            'success': True, 'rule_name': result.name,
            'server_name': server_name,
            'start_ip': result.start_ip_address, 'end_ip': result.end_ip_address,
            'message': f'Successfully created firewall rule {result.name} on {server_name}'
        }
    except Exception as e:
        logger.error(f"Error creating SQL firewall rule: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


# ==================== CONTAINER INSTANCE LIFECYCLE ====================


def create_container_instance(
    resource_group: str,
    container_group_name: str,
    image: str,
    location: str,
    cpu: float = 1.0,
    memory_gb: float = 1.5,
    port: int = 80,
    os_type: str = 'Linux',
    restart_policy: str = 'Always',
    env_vars: Optional[Dict[str, str]] = None,
    tags: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Create an Azure Container Instance."""
    try:
        container_client = _get_azure_client('container')

        container_resource = {
            'requests': {'cpu': cpu, 'memory_in_gb': memory_gb}
        }
        container_def = {
            'name': container_group_name,
            'image': image,
            'resources': container_resource,
            'ports': [{'port': port}],
        }
        if env_vars:
            container_def['environment_variables'] = [
                {'name': k, 'value': v} for k, v in env_vars.items()
            ]

        params = {
            'location': location,
            'containers': [container_def],
            'os_type': os_type,
            'restart_policy': restart_policy,
            'ip_address': {'type': 'Public', 'ports': [{'protocol': 'TCP', 'port': port}]},
        }
        if tags:
            params['tags'] = tags

        result = container_client.container_groups.begin_create_or_update(
            resource_group, container_group_name, params
        ).result()

        ip = result.ip_address.ip if result.ip_address else None
        return {
            'success': True, 'name': result.name, 'location': result.location,
            'provisioning_state': result.provisioning_state,
            'ip_address': ip, 'image': image,
            'message': f'Successfully created container instance {result.name}'
        }
    except Exception as e:
        logger.error(f"Error creating Azure Container Instance: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


def delete_container_instance(resource_group: str, container_group_name: str) -> Dict[str, Any]:
    """Delete an Azure Container Instance."""
    try:
        container_client = _get_azure_client('container')
        container_client.container_groups.begin_delete(resource_group, container_group_name).result()
        return {
            'success': True, 'name': container_group_name, 'resource_group': resource_group,
            'message': f'Successfully deleted container instance {container_group_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting Azure Container Instance: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


def restart_container_instance(resource_group: str, container_group_name: str) -> Dict[str, Any]:
    """Restart an Azure Container Instance."""
    try:
        container_client = _get_azure_client('container')
        container_client.container_groups.begin_restart(resource_group, container_group_name).result()
        return {
            'success': True, 'name': container_group_name, 'resource_group': resource_group,
            'message': f'Successfully restarted container instance {container_group_name}'
        }
    except Exception as e:
        logger.error(f"Error restarting Azure Container Instance: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


# ==================== DISK MANAGEMENT ====================


def list_managed_disks(resource_group: str) -> Dict[str, Any]:
    """List managed disks in a resource group."""
    try:
        compute_client = _get_azure_client('compute')
        disks = []
        for disk in compute_client.disks.list_by_resource_group(resource_group):
            disks.append({
                'name': disk.name,
                'location': disk.location,
                'size_gb': disk.disk_size_gb,
                'sku': disk.sku.name if disk.sku else None,
                'state': disk.disk_state,
                'os_type': disk.os_type,
                'provisioning_state': disk.provisioning_state,
                'managed_by': disk.managed_by,
                'tags': disk.tags or {}
            })
        return {'success': True, 'count': len(disks), 'disks': disks, 'resource_group': resource_group}
    except Exception as e:
        logger.error(f"Error listing Azure managed disks: {str(e)}")
        return {'success': False, 'error': str(e)}


def create_managed_disk(
    resource_group: str,
    disk_name: str,
    location: str,
    size_gb: int = 32,
    sku_name: str = 'Standard_LRS',
    tags: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Create a managed disk."""
    try:
        compute_client = _get_azure_client('compute')
        params = {
            'location': location,
            'disk_size_gb': size_gb,
            'creation_data': {'create_option': 'Empty'},
            'sku': {'name': sku_name},
        }
        if tags:
            params['tags'] = tags

        result = compute_client.disks.begin_create_or_update(resource_group, disk_name, params).result()
        return {
            'success': True, 'disk_name': result.name, 'location': result.location,
            'size_gb': result.disk_size_gb, 'sku': result.sku.name,
            'provisioning_state': result.provisioning_state,
            'message': f'Successfully created managed disk {result.name} ({size_gb}GB)'
        }
    except Exception as e:
        logger.error(f"Error creating Azure managed disk: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


def delete_managed_disk(resource_group: str, disk_name: str) -> Dict[str, Any]:
    """Delete a managed disk."""
    try:
        compute_client = _get_azure_client('compute')
        compute_client.disks.begin_delete(resource_group, disk_name).result()
        return {
            'success': True, 'disk_name': disk_name, 'resource_group': resource_group,
            'message': f'Successfully deleted managed disk {disk_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting Azure managed disk: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


# ==================== VIRTUAL NETWORK OPERATIONS ====================


def list_virtual_networks(resource_group: Optional[str] = None) -> Dict[str, Any]:
    """List Azure Virtual Networks."""
    try:
        network_client = _get_azure_client('network')
        vnets = []
        if resource_group:
            vnet_list = network_client.virtual_networks.list(resource_group)
        else:
            vnet_list = network_client.virtual_networks.list_all()

        for vnet in vnet_list:
            subnets = []
            if vnet.subnets:
                for subnet in vnet.subnets:
                    subnets.append({
                        'name': subnet.name,
                        'address_prefix': subnet.address_prefix,
                        'provisioning_state': subnet.provisioning_state,
                    })

            vnets.append({
                'name': vnet.name,
                'location': vnet.location,
                'resource_group': vnet.id.split('/')[4],
                'address_space': vnet.address_space.address_prefixes if vnet.address_space else [],
                'subnets': subnets,
                'provisioning_state': vnet.provisioning_state,
                'tags': vnet.tags or {}
            })

        return {'success': True, 'count': len(vnets), 'virtual_networks': vnets}
    except Exception as e:
        logger.error(f"Error listing Azure VNets: {str(e)}")
        return {'success': False, 'error': str(e)}


def create_virtual_network(
    resource_group: str,
    vnet_name: str,
    location: str,
    address_prefix: str = '10.0.0.0/16',
    subnet_name: Optional[str] = None,
    subnet_prefix: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Create a Virtual Network with an optional subnet."""
    try:
        network_client = _get_azure_client('network')
        params = {
            'location': location,
            'address_space': {'address_prefixes': [address_prefix]},
        }
        if subnet_name and subnet_prefix:
            params['subnets'] = [{'name': subnet_name, 'address_prefix': subnet_prefix}]
        if tags:
            params['tags'] = tags

        result = network_client.virtual_networks.begin_create_or_update(
            resource_group, vnet_name, params
        ).result()

        subnets = [s.name for s in result.subnets] if result.subnets else []
        return {
            'success': True, 'vnet_name': result.name, 'location': result.location,
            'address_space': result.address_space.address_prefixes,
            'subnets': subnets, 'resource_group': resource_group,
            'message': f'Successfully created VNet {result.name}'
        }
    except Exception as e:
        logger.error(f"Error creating Azure VNet: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


# ==================== PUBLIC IP OPERATIONS ====================


def list_public_ips(resource_group: Optional[str] = None) -> Dict[str, Any]:
    """List Azure Public IP addresses."""
    try:
        network_client = _get_azure_client('network')
        ips = []
        if resource_group:
            ip_list = network_client.public_ip_addresses.list(resource_group)
        else:
            ip_list = network_client.public_ip_addresses.list_all()

        for ip in ip_list:
            ips.append({
                'name': ip.name,
                'location': ip.location,
                'resource_group': ip.id.split('/')[4],
                'ip_address': ip.ip_address,
                'allocation_method': ip.public_ip_allocation_method,
                'sku': ip.sku.name if ip.sku else None,
                'provisioning_state': ip.provisioning_state,
                'tags': ip.tags or {}
            })

        return {'success': True, 'count': len(ips), 'public_ips': ips}
    except Exception as e:
        logger.error(f"Error listing Azure public IPs: {str(e)}")
        return {'success': False, 'error': str(e)}


def delete_public_ip(resource_group: str, public_ip_name: str) -> Dict[str, Any]:
    """Delete an Azure Public IP address."""
    try:
        network_client = _get_azure_client('network')
        network_client.public_ip_addresses.begin_delete(resource_group, public_ip_name).result()
        return {
            'success': True, 'public_ip_name': public_ip_name, 'resource_group': resource_group,
            'message': f'Successfully deleted public IP {public_ip_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting Azure public IP: {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


_AZURE_READ_PREFIXES = ('list', 'get', 'check', 'validate', 'begin_list', 'begin_get')


def _is_azure_read(operation: str) -> bool:
    op = operation.lower().split('.')[-1]
    return any(op.startswith(p) for p in _AZURE_READ_PREFIXES)


def _azure_execute(client_type: str, operation_path: str, params: Optional[Dict[str, Any]]) -> Any:
    """Navigate Azure SDK client hierarchy and call a method. Handles paged iterators."""
    client = _get_azure_client(client_type)
    if client is None:
        raise Exception(f'Unknown Azure client type: "{client_type}". '
                        'Valid values: compute, storage, network, resource, monitor, container, sql')
    parts = operation_path.strip().split('.')
    obj = client
    for part in parts[:-1]:
        obj = getattr(obj, part)
    method = getattr(obj, parts[-1])
    result = method(**(params or {}))
    # Handle Azure paged iterators
    if hasattr(result, '__iter__') and hasattr(result, 'by_page'):
        items = [r.as_dict() if hasattr(r, 'as_dict') else str(r) for r in result]
        return items
    # Handle LRO pollers (begin_* methods)
    if hasattr(result, 'result'):
        final = result.result()
        return final.as_dict() if hasattr(final, 'as_dict') else str(final)
    if hasattr(result, 'as_dict'):
        return result.as_dict()
    return result


def azure_api_read(
    client_type: str,
    operation_path: str,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Call ANY Azure read-only SDK operation (list/get/check) when no dedicated tool exists.

    Examples:
      azure_api_read('compute', 'virtual_machine_scale_sets.list', {'resource_group_name': 'my-rg'})
      azure_api_read('network', 'application_gateways.list_all', {})
      azure_api_read('monitor', 'alert_rules.list_by_resource_group', {'resource_group_name': 'my-rg'})
    """
    if not _is_azure_read(operation_path):
        return {'success': False, 'error': f'"{operation_path}" does not look like a read operation. Use azure_api_write for create/update/delete.'}
    try:
        result = _azure_execute(client_type, operation_path, params)
        return {'success': True, 'client_type': client_type, 'operation': operation_path, 'result': result}
    except Exception as e:
        logger.error(f"azure_api_read error ({client_type}.{operation_path}): {str(e)}")
        return {'success': False, 'error': str(e)}


def azure_api_write(
    client_type: str,
    operation_path: str,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Call ANY Azure write SDK operation (create/update/delete/begin_*) when no dedicated tool exists.
    Requires user confirmation. Always confirm operation and params before calling.

    Examples:
      azure_api_write('compute', 'virtual_machines.begin_deallocate', {'resource_group_name': 'my-rg', 'vm_name': 'my-vm'})
      azure_api_write('network', 'load_balancers.begin_delete', {'resource_group_name': 'my-rg', 'load_balancer_name': 'my-lb'})
      azure_api_write('monitor', 'metric_alerts.create_or_update', {'resource_group_name': 'rg', 'rule_name': 'cpu-alert', 'parameters': {...}})
    """
    if _is_azure_read(operation_path):
        return {'success': False, 'error': f'"{operation_path}" looks like a read operation. Use azure_api_read instead.'}
    try:
        result = _azure_execute(client_type, operation_path, params)
        return {'success': True, 'client_type': client_type, 'operation': operation_path, 'result': result,
                'message': f'Successfully executed {client_type}.{operation_path}'}
    except Exception as e:
        logger.error(f"azure_api_write error ({client_type}.{operation_path}): {str(e)}")
        return {'success': False, 'error': _friendly_azure_error(e)}


# ==================== TOOL REGISTRATION ====================


def get_tools() -> List[Dict[str, Any]]:
    """
    Get list of Azure tool definitions for the agent.

    Returns:
        List of tool definitions with name, description, input_schema, and handler
    """
    return [
        # Resource Group Operations
        {
            'name': 'list_resource_groups',
            'description': 'List all Azure Resource Groups in the subscription',
            'input_schema': {
                'type': 'object',
                'properties': {}
            },
            'handler': list_resource_groups
        },
        {
            'name': 'create_resource_group',
            'description': 'Create a new Azure Resource Group',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group_name': {
                        'type': 'string',
                        'description': 'Name for the resource group'
                    },
                    'location': {
                        'type': 'string',
                        'description': 'Azure region (e.g., eastus, westus2, westeurope, southeastasia)'
                    },
                    'tags': {
                        'type': 'object',
                        'description': 'Optional tags as key-value pairs'
                    }
                },
                'required': ['resource_group_name', 'location']
            },
            'handler': create_resource_group
        },
        {
            'name': 'delete_resource_group',
            'description': 'Delete an Azure Resource Group and ALL its resources (WARNING: Destructive operation!)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group_name': {
                        'type': 'string',
                        'description': 'Name of the resource group to delete'
                    },
                    'force': {
                        'type': 'boolean',
                        'description': 'If true, skip confirmation (default: false)',
                        'default': False
                    }
                },
                'required': ['resource_group_name']
            },
            'handler': delete_resource_group
        },
        # Virtual Machine Operations
        {
            'name': 'list_virtual_machines',
            'description': 'List Azure Virtual Machines (optionally filtered by resource group)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {
                        'type': 'string',
                        'description': 'Optional resource group name to filter VMs'
                    }
                }
            },
            'handler': list_virtual_machines
        },
        {
            'name': 'get_vm_details',
            'description': 'Get detailed information about a specific Azure VM',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {
                        'type': 'string',
                        'description': 'Resource group name'
                    },
                    'vm_name': {
                        'type': 'string',
                        'description': 'Virtual machine name'
                    }
                },
                'required': ['resource_group', 'vm_name']
            },
            'handler': get_vm_details
        },
        {
            'name': 'manage_vm',
            'description': 'Manage Azure VM (start, stop, restart, deallocate)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {
                        'type': 'string',
                        'description': 'Resource group name'
                    },
                    'vm_name': {
                        'type': 'string',
                        'description': 'Virtual machine name'
                    },
                    'action': {
                        'type': 'string',
                        'description': 'Action to perform: start, stop, restart, deallocate',
                        'enum': ['start', 'stop', 'restart', 'deallocate']
                    }
                },
                'required': ['resource_group', 'vm_name', 'action']
            },
            'handler': manage_vm
        },
        {
            'name': 'create_virtual_machine',
            'description': 'Create a new Azure Virtual Machine with networking components',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {
                        'type': 'string',
                        'description': 'Resource group name (must exist)'
                    },
                    'vm_name': {
                        'type': 'string',
                        'description': 'Name for the virtual machine'
                    },
                    'location': {
                        'type': 'string',
                        'description': 'Azure region (e.g., eastus, westus2)'
                    },
                    'vm_size': {
                        'type': 'string',
                        'description': 'VM size (e.g., Standard_B1s, Standard_D2s_v3, Standard_E2s_v3)'
                    },
                    'admin_username': {
                        'type': 'string',
                        'description': 'Administrator username'
                    },
                    'admin_password': {
                        'type': 'string',
                        'description': 'Administrator password (must be 12-72 characters)'
                    },
                    'image_publisher': {
                        'type': 'string',
                        'description': 'Image publisher (default: Canonical for Ubuntu)',
                        'default': 'Canonical'
                    },
                    'image_offer': {
                        'type': 'string',
                        'description': 'Image offer (default: UbuntuServer)',
                        'default': 'UbuntuServer'
                    },
                    'image_sku': {
                        'type': 'string',
                        'description': 'Image SKU (default: 18.04-LTS)',
                        'default': '18.04-LTS'
                    },
                    'os_disk_size_gb': {
                        'type': 'integer',
                        'description': 'OS disk size in GB (default: 30)',
                        'default': 30
                    },
                    'tags': {
                        'type': 'object',
                        'description': 'Optional tags'
                    }
                },
                'required': ['resource_group', 'vm_name', 'location', 'vm_size', 'admin_username', 'admin_password']
            },
            'handler': create_virtual_machine
        },
        {
            'name': 'delete_virtual_machine',
            'description': 'Delete an Azure Virtual Machine',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {
                        'type': 'string',
                        'description': 'Resource group name'
                    },
                    'vm_name': {
                        'type': 'string',
                        'description': 'Virtual machine name'
                    }
                },
                'required': ['resource_group', 'vm_name']
            },
            'handler': delete_virtual_machine
        },
        # Storage Account Operations
        {
            'name': 'list_storage_accounts',
            'description': 'List Azure Storage Accounts (optionally filtered by resource group)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {
                        'type': 'string',
                        'description': 'Optional resource group name to filter storage accounts'
                    }
                }
            },
            'handler': list_storage_accounts
        },
        {
            'name': 'create_storage_account',
            'description': 'Create a new Azure Storage Account',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {
                        'type': 'string',
                        'description': 'Resource group name'
                    },
                    'storage_account_name': {
                        'type': 'string',
                        'description': 'Storage account name (must be globally unique, 3-24 lowercase alphanumeric characters)'
                    },
                    'location': {
                        'type': 'string',
                        'description': 'Azure region'
                    },
                    'sku_name': {
                        'type': 'string',
                        'description': 'SKU name: Standard_LRS, Standard_GRS, Standard_RAGRS, Premium_LRS (default: Standard_LRS)',
                        'default': 'Standard_LRS'
                    },
                    'kind': {
                        'type': 'string',
                        'description': 'Storage account kind: StorageV2, Storage, BlobStorage (default: StorageV2)',
                        'default': 'StorageV2'
                    },
                    'tags': {
                        'type': 'object',
                        'description': 'Optional tags'
                    }
                },
                'required': ['resource_group', 'storage_account_name', 'location']
            },
            'handler': create_storage_account
        },
        # SQL Server Operations
        {
            'name': 'list_sql_servers',
            'description': 'List Azure SQL Servers (optionally filtered by resource group)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {
                        'type': 'string',
                        'description': 'Optional resource group name to filter SQL servers'
                    }
                }
            },
            'handler': list_sql_servers
        },
        {
            'name': 'list_sql_databases',
            'description': 'List databases on an Azure SQL Server',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {
                        'type': 'string',
                        'description': 'Resource group name'
                    },
                    'server_name': {
                        'type': 'string',
                        'description': 'SQL server name'
                    }
                },
                'required': ['resource_group', 'server_name']
            },
            'handler': list_sql_databases
        },
        {
            'name': 'create_sql_server',
            'description': 'Create a new Azure SQL Server',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {
                        'type': 'string',
                        'description': 'Resource group name'
                    },
                    'server_name': {
                        'type': 'string',
                        'description': 'SQL server name (must be globally unique)'
                    },
                    'location': {
                        'type': 'string',
                        'description': 'Azure region'
                    },
                    'admin_username': {
                        'type': 'string',
                        'description': 'Administrator username'
                    },
                    'admin_password': {
                        'type': 'string',
                        'description': 'Administrator password (must meet complexity requirements: 8+ chars, uppercase, lowercase, digit, special char)'
                    },
                    'version': {
                        'type': 'string',
                        'description': 'SQL Server version (default: 12.0)',
                        'default': '12.0'
                    },
                    'tags': {
                        'type': 'object',
                        'description': 'Optional tags'
                    }
                },
                'required': ['resource_group', 'server_name', 'location', 'admin_username', 'admin_password']
            },
            'handler': create_sql_server
        },
        {
            'name': 'create_sql_database',
            'description': 'Create a new Azure SQL Database on an existing SQL Server',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {
                        'type': 'string',
                        'description': 'Resource group name'
                    },
                    'server_name': {
                        'type': 'string',
                        'description': 'SQL server name (must exist)'
                    },
                    'database_name': {
                        'type': 'string',
                        'description': 'Database name'
                    },
                    'location': {
                        'type': 'string',
                        'description': 'Azure region (must match server location)'
                    },
                    'sku_name': {
                        'type': 'string',
                        'description': 'SKU name: Basic, S0, S1, S2, P1, P2, etc. (default: Basic)',
                        'default': 'Basic'
                    },
                    'sku_tier': {
                        'type': 'string',
                        'description': 'SKU tier: Basic, Standard, Premium (default: Basic)',
                        'default': 'Basic'
                    },
                    'max_size_bytes': {
                        'type': 'integer',
                        'description': 'Maximum database size in bytes (default: 2GB = 2147483648)',
                        'default': 2147483648
                    },
                    'tags': {
                        'type': 'object',
                        'description': 'Optional tags'
                    }
                },
                'required': ['resource_group', 'server_name', 'database_name', 'location']
            },
            'handler': create_sql_database
        },
        # Container Instances
        {
            'name': 'list_container_instances',
            'description': 'List Azure Container Instances (ACI)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {
                        'type': 'string',
                        'description': 'Optional resource group name to filter container instances'
                    }
                }
            },
            'handler': list_container_instances
        },
        # Azure Monitor
        {
            'name': 'get_azure_metrics',
            'description': 'Get Azure Monitor metrics for a resource',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_id': {
                        'type': 'string',
                        'description': 'Full resource ID (e.g., /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{vm})'
                    },
                    'metric_names': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'List of metric names (e.g., Percentage CPU, Network In)'
                    },
                    'timespan': {
                        'type': 'string',
                        'description': 'Time span in ISO 8601 duration format (e.g., PT1H for 1 hour, PT24H for 24 hours)'
                    },
                    'aggregation': {
                        'type': 'string',
                        'description': 'Aggregation type (e.g., Average, Total, Maximum)'
                    }
                },
                'required': ['resource_id', 'metric_names']
            },
            'handler': get_azure_metrics
        },
        # ---- Storage Lifecycle ----
        {
            'name': 'delete_storage_account',
            'description': 'Delete an Azure Storage Account.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group name'},
                    'storage_account_name': {'type': 'string', 'description': 'Storage account name'}
                },
                'required': ['resource_group', 'storage_account_name']
            },
            'handler': delete_storage_account
        },
        {
            'name': 'list_storage_account_keys',
            'description': 'List access keys for an Azure Storage Account.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group name'},
                    'storage_account_name': {'type': 'string', 'description': 'Storage account name'}
                },
                'required': ['resource_group', 'storage_account_name']
            },
            'handler': list_storage_account_keys
        },
        {
            'name': 'regenerate_storage_key',
            'description': 'Regenerate (rotate) a storage account access key.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group name'},
                    'storage_account_name': {'type': 'string', 'description': 'Storage account name'},
                    'key_name': {'type': 'string', 'enum': ['key1', 'key2'], 'description': 'Key to regenerate', 'default': 'key1'}
                },
                'required': ['resource_group', 'storage_account_name']
            },
            'handler': regenerate_storage_key
        },
        # ---- Network Security Groups ----
        {
            'name': 'list_network_security_groups',
            'description': 'List Azure Network Security Groups with their rules.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group (optional, lists all if omitted)'}
                }
            },
            'handler': list_network_security_groups
        },
        {
            'name': 'create_network_security_group',
            'description': 'Create an Azure Network Security Group.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group name'},
                    'nsg_name': {'type': 'string', 'description': 'NSG name'},
                    'location': {'type': 'string', 'description': 'Azure region'},
                    'tags': {'type': 'object', 'description': 'Optional tags'}
                },
                'required': ['resource_group', 'nsg_name', 'location']
            },
            'handler': create_network_security_group
        },
        {
            'name': 'create_nsg_rule',
            'description': 'Create a security rule in a Network Security Group (firewall rule).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group name'},
                    'nsg_name': {'type': 'string', 'description': 'NSG name'},
                    'rule_name': {'type': 'string', 'description': 'Rule name'},
                    'priority': {'type': 'integer', 'description': 'Priority (100-4096, lower = higher priority)'},
                    'direction': {'type': 'string', 'enum': ['Inbound', 'Outbound'], 'default': 'Inbound'},
                    'access': {'type': 'string', 'enum': ['Allow', 'Deny'], 'default': 'Allow'},
                    'protocol': {'type': 'string', 'enum': ['Tcp', 'Udp', 'Icmp', '*'], 'default': 'Tcp'},
                    'source_address': {'type': 'string', 'description': 'Source IP/CIDR (* for any)', 'default': '*'},
                    'source_port': {'type': 'string', 'description': 'Source port range', 'default': '*'},
                    'destination_address': {'type': 'string', 'description': 'Destination IP/CIDR', 'default': '*'},
                    'destination_port': {'type': 'string', 'description': 'Destination port (e.g., "80", "443", "22")'}
                },
                'required': ['resource_group', 'nsg_name', 'rule_name', 'priority', 'destination_port']
            },
            'handler': create_nsg_rule
        },
        {
            'name': 'delete_network_security_group',
            'description': 'Delete an Azure Network Security Group.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group name'},
                    'nsg_name': {'type': 'string', 'description': 'NSG name'}
                },
                'required': ['resource_group', 'nsg_name']
            },
            'handler': delete_network_security_group
        },
        # ---- SQL Lifecycle ----
        {
            'name': 'delete_sql_server',
            'description': 'Delete an Azure SQL Server and all its databases.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group name'},
                    'server_name': {'type': 'string', 'description': 'SQL server name'}
                },
                'required': ['resource_group', 'server_name']
            },
            'handler': delete_sql_server
        },
        {
            'name': 'delete_sql_database',
            'description': 'Delete an Azure SQL Database.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group name'},
                    'server_name': {'type': 'string', 'description': 'SQL server name'},
                    'database_name': {'type': 'string', 'description': 'Database name'}
                },
                'required': ['resource_group', 'server_name', 'database_name']
            },
            'handler': delete_sql_database
        },
        {
            'name': 'create_sql_firewall_rule',
            'description': 'Create a firewall rule on an Azure SQL Server to allow IP access.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group name'},
                    'server_name': {'type': 'string', 'description': 'SQL server name'},
                    'rule_name': {'type': 'string', 'description': 'Firewall rule name'},
                    'start_ip': {'type': 'string', 'description': 'Start IP address'},
                    'end_ip': {'type': 'string', 'description': 'End IP address (same as start for single IP)'}
                },
                'required': ['resource_group', 'server_name', 'rule_name', 'start_ip', 'end_ip']
            },
            'handler': create_sql_firewall_rule
        },
        # ---- Container Instance Lifecycle ----
        {
            'name': 'create_container_instance',
            'description': 'Create an Azure Container Instance (serverless container).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group name'},
                    'container_group_name': {'type': 'string', 'description': 'Container group name'},
                    'image': {'type': 'string', 'description': 'Container image (e.g., "nginx:latest")'},
                    'location': {'type': 'string', 'description': 'Azure region'},
                    'cpu': {'type': 'number', 'description': 'CPU cores (default: 1.0)', 'default': 1.0},
                    'memory_gb': {'type': 'number', 'description': 'Memory in GB (default: 1.5)', 'default': 1.5},
                    'port': {'type': 'integer', 'description': 'Container port (default: 80)', 'default': 80},
                    'os_type': {'type': 'string', 'enum': ['Linux', 'Windows'], 'default': 'Linux'},
                    'restart_policy': {'type': 'string', 'enum': ['Always', 'Never', 'OnFailure'], 'default': 'Always'},
                    'env_vars': {'type': 'object', 'description': 'Environment variables as key-value pairs'},
                    'tags': {'type': 'object', 'description': 'Optional tags'}
                },
                'required': ['resource_group', 'container_group_name', 'image', 'location']
            },
            'handler': create_container_instance
        },
        {
            'name': 'delete_container_instance',
            'description': 'Delete an Azure Container Instance.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group name'},
                    'container_group_name': {'type': 'string', 'description': 'Container group name'}
                },
                'required': ['resource_group', 'container_group_name']
            },
            'handler': delete_container_instance
        },
        {
            'name': 'restart_container_instance',
            'description': 'Restart an Azure Container Instance.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group name'},
                    'container_group_name': {'type': 'string', 'description': 'Container group name'}
                },
                'required': ['resource_group', 'container_group_name']
            },
            'handler': restart_container_instance
        },
        # ---- Disk Management ----
        {
            'name': 'list_managed_disks',
            'description': 'List managed disks in a resource group.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group name'}
                },
                'required': ['resource_group']
            },
            'handler': list_managed_disks
        },
        {
            'name': 'create_managed_disk',
            'description': 'Create an Azure managed disk.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group name'},
                    'disk_name': {'type': 'string', 'description': 'Disk name'},
                    'location': {'type': 'string', 'description': 'Azure region'},
                    'size_gb': {'type': 'integer', 'description': 'Disk size in GB (default: 32)', 'default': 32},
                    'sku_name': {'type': 'string', 'enum': ['Standard_LRS', 'Premium_LRS', 'StandardSSD_LRS'], 'default': 'Standard_LRS'},
                    'tags': {'type': 'object', 'description': 'Optional tags'}
                },
                'required': ['resource_group', 'disk_name', 'location']
            },
            'handler': create_managed_disk
        },
        {
            'name': 'delete_managed_disk',
            'description': 'Delete an Azure managed disk.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group name'},
                    'disk_name': {'type': 'string', 'description': 'Disk name'}
                },
                'required': ['resource_group', 'disk_name']
            },
            'handler': delete_managed_disk
        },
        # ---- Virtual Network ----
        {
            'name': 'list_virtual_networks',
            'description': 'List Azure Virtual Networks with subnets and address spaces.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group (optional, lists all if omitted)'}
                }
            },
            'handler': list_virtual_networks
        },
        {
            'name': 'create_virtual_network',
            'description': 'Create an Azure Virtual Network with optional subnet.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group name'},
                    'vnet_name': {'type': 'string', 'description': 'VNet name'},
                    'location': {'type': 'string', 'description': 'Azure region'},
                    'address_prefix': {'type': 'string', 'description': 'Address space CIDR (default: 10.0.0.0/16)', 'default': '10.0.0.0/16'},
                    'subnet_name': {'type': 'string', 'description': 'Subnet name (optional)'},
                    'subnet_prefix': {'type': 'string', 'description': 'Subnet CIDR (e.g., 10.0.1.0/24)'},
                    'tags': {'type': 'object', 'description': 'Optional tags'}
                },
                'required': ['resource_group', 'vnet_name', 'location']
            },
            'handler': create_virtual_network
        },
        # ---- Public IP ----
        {
            'name': 'list_public_ips',
            'description': 'List Azure Public IP addresses.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group (optional, lists all if omitted)'}
                }
            },
            'handler': list_public_ips
        },
        {
            'name': 'delete_public_ip',
            'description': 'Delete an Azure Public IP address.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_group': {'type': 'string', 'description': 'Resource group name'},
                    'public_ip_name': {'type': 'string', 'description': 'Public IP name'}
                },
                'required': ['resource_group', 'public_ip_name']
            },
            'handler': delete_public_ip
        },
        {
            'name': 'azure_api_read',
            'description': (
                'Call ANY Azure read-only SDK operation (list/get/check) when no dedicated tool exists. '
                'client_type: compute, storage, network, resource, monitor, container, sql. '
                'operation_path: dot-separated SDK path e.g. "virtual_machine_scale_sets.list", '
                '"application_gateways.list_all", "alert_rules.list_by_resource_group", '
                '"managed_disks.list_by_resource_group", "availability_sets.list". '
                'Never use for create/update/delete — use azure_api_write for those.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'client_type': {'type': 'string', 'enum': ['compute', 'storage', 'network', 'resource', 'monitor', 'container', 'sql'], 'description': 'Azure SDK client type'},
                    'operation_path': {'type': 'string', 'description': 'Dot-separated SDK path e.g. virtual_machine_scale_sets.list'},
                    'params': {'type': 'object', 'description': 'Method parameters e.g. {"resource_group_name": "my-rg"}'}
                },
                'required': ['client_type', 'operation_path']
            },
            'handler': azure_api_read
        },
        {
            'name': 'azure_api_write',
            'description': (
                'Call ANY Azure write SDK operation (create_or_update/begin_delete/begin_create/update) when no dedicated tool exists. '
                'Requires user confirmation. '
                'Examples: "virtual_machines.begin_deallocate", "load_balancers.begin_delete", '
                '"metric_alerts.create_or_update", "network_security_groups.begin_create_or_update".'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'client_type': {'type': 'string', 'enum': ['compute', 'storage', 'network', 'resource', 'monitor', 'container', 'sql'], 'description': 'Azure SDK client type'},
                    'operation_path': {'type': 'string', 'description': 'Dot-separated SDK path e.g. virtual_machines.begin_deallocate'},
                    'params': {'type': 'object', 'description': 'Method parameters'}
                },
                'required': ['client_type', 'operation_path']
            },
            'handler': azure_api_write
        },
    ]
