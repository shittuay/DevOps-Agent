"""Azure tools for DevOps Agent."""
from typing import Dict, Any, List, Optional
from ..utils import get_logger

logger = get_logger(__name__)


def _get_azure_client(service_type: str, credential=None):
    """
    Get Azure client for specified service.

    Args:
        service_type: Type of Azure service (compute, storage, network, etc.)
        credential: Azure credential object

    Returns:
        Azure client instance
    """
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.compute import ComputeManagementClient
        from azure.mgmt.storage import StorageManagementClient
        from azure.mgmt.network import NetworkManagementClient
        from azure.mgmt.resource import ResourceManagementClient
        from azure.mgmt.monitor import MonitorManagementClient
        from azure.mgmt.containerinstance import ContainerInstanceManagementClient
        from azure.mgmt.sql import SqlManagementClient
        import os

        if credential is None:
            credential = DefaultAzureCredential()

        subscription_id = os.environ.get('AZURE_SUBSCRIPTION_ID')
        if not subscription_id:
            raise Exception("AZURE_SUBSCRIPTION_ID not found in environment variables")

        clients = {
            'compute': ComputeManagementClient(credential, subscription_id),
            'storage': StorageManagementClient(credential, subscription_id),
            'network': NetworkManagementClient(credential, subscription_id),
            'resource': ResourceManagementClient(credential, subscription_id),
            'monitor': MonitorManagementClient(credential, subscription_id),
            'container': ContainerInstanceManagementClient(credential, subscription_id),
            'sql': SqlManagementClient(credential, subscription_id),
        }

        return clients.get(service_type)
    except ImportError:
        raise Exception("Azure SDK not installed. Install with: pip install azure-mgmt-compute azure-mgmt-storage azure-mgmt-network azure-mgmt-resource azure-mgmt-monitor azure-identity")
    except Exception as e:
        raise Exception(f"Failed to create Azure client: {str(e)}")


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
        return {'success': False, 'error': str(e)}


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
    aggregation: str = 'Average'
) -> Dict[str, Any]:
    """
    Get Azure Monitor metrics for a resource.

    Args:
        resource_id: Full Azure resource ID
        metric_names: List of metric names to retrieve
        timespan: ISO 8601 timespan (e.g., 'PT1H' for last hour)
        aggregation: Aggregation type (Average, Total, Minimum, Maximum)

    Returns:
        Dictionary with metrics data
    """
    try:
        from azure.identity import DefaultAzureCredential
        from azure.monitor.query import MetricsQueryClient
        from datetime import datetime, timedelta

        credential = DefaultAzureCredential()
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
        return {'success': False, 'error': str(e)}


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
        return {'success': False, 'error': str(e)}


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
        return {'success': False, 'error': str(e)}


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
        return {'success': False, 'error': str(e)}


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
        return {'success': False, 'error': str(e)}


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
        return {'success': False, 'error': str(e)}


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
        return {'success': False, 'error': str(e)}

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
        }
    ]
