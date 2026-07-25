"""Google Cloud Platform tools for DevOps Agent."""
import os
from typing import Dict, Any, List, Optional
from ..utils import get_logger

logger = get_logger(__name__)


def _get_current_user_id() -> Optional[int]:
    """Get current user ID from Flask context if available."""
    try:
        from flask import g, has_request_context
        if has_request_context() and hasattr(g, 'current_user_id'):
            return g.current_user_id
    except ImportError:
        pass
    return None


def _get_user_gcp_credentials():
    """
    Get per-user GCP credentials from the database.
    Returns (credentials, project_id) or (None, None).
    """
    user_id = _get_current_user_id()
    if not user_id:
        return None, None

    try:
        from services.credential_service import get_user_gcp_credentials_file
        import json
        from google.oauth2 import service_account

        creds_path, project_id, region, zone = get_user_gcp_credentials_file(user_id)
        try:
            credentials = service_account.Credentials.from_service_account_file(creds_path)
        finally:
            # Always clean up the temp file (contains a plaintext private key),
            # even if loading it fails partway through.
            try:
                os.remove(creds_path)
            except OSError:
                pass

        return credentials, project_id
    except Exception:
        return None, None


def _resolve_project_id(project_id: Optional[str] = None) -> str:
    """Resolve GCP project ID: explicit > per-user credentials > env var."""
    if project_id:
        return project_id
    _, user_project = _get_user_gcp_credentials()
    if user_project:
        return user_project
    env_project = os.environ.get('GCP_PROJECT_ID')
    if env_project:
        return env_project
    raise Exception("GCP credentials not configured. Please configure your GCP credentials in Settings.")


def _get_gcp_client(service_type: str, project_id: Optional[str] = None):
    """
    Get GCP client for specified service using per-user credentials when available.

    Args:
        service_type: Type of GCP service
        project_id: GCP project ID

    Returns:
        Tuple of (GCP client instance, project_id)
    """
    try:
        from google.cloud import compute_v1, storage, container_v1, sql_v1, monitoring_v3

        # Try per-user credentials first
        user_credentials, user_project = _get_user_gcp_credentials()

        if project_id is None:
            project_id = user_project or os.environ.get('GCP_PROJECT_ID')
            if not project_id:
                raise Exception(
                    "GCP credentials not configured. Please configure your GCP credentials in Settings."
                )

        # Build clients with per-user credentials if available
        creds_kwargs = {'credentials': user_credentials} if user_credentials else {}

        clients = {
            'compute': compute_v1.InstancesClient(**creds_kwargs),
            'storage': storage.Client(project=project_id, **creds_kwargs),
            'container': container_v1.ClusterManagerClient(**creds_kwargs),
            'sql': sql_v1.SqlInstancesServiceClient(**creds_kwargs),
            'monitoring': monitoring_v3.MetricServiceClient(**creds_kwargs)
        }

        return clients.get(service_type), project_id
    except ImportError:
        raise Exception("Google Cloud SDK not installed. Install with: pip install google-cloud-compute google-cloud-storage google-cloud-container google-cloud-sql google-cloud-monitoring")
    except Exception as e:
        raise Exception(f"Failed to create GCP client: {str(e)}")


def list_compute_instances(
    project_id: Optional[str] = None,
    zone: Optional[str] = None
) -> Dict[str, Any]:
    """
    List Google Compute Engine instances.

    Args:
        project_id: GCP project ID
        zone: GCP zone (e.g., 'us-central1-a')

    Returns:
        Dictionary with instance information
    """
    try:
        from google.cloud import compute_v1

        client, proj_id = _get_gcp_client('compute', project_id)

        instances = []

        if zone:
            # List instances in specific zone
            request = compute_v1.ListInstancesRequest(
                project=proj_id,
                zone=zone
            )
            instance_list = client.list(request=request)

            for instance in instance_list:
                instances.append(_format_gce_instance(instance, zone))
        else:
            # List instances in all zones
            zones_client = compute_v1.ZonesClient()
            zones_request = compute_v1.ListZonesRequest(project=proj_id)

            for zone_info in zones_client.list(request=zones_request):
                request = compute_v1.ListInstancesRequest(
                    project=proj_id,
                    zone=zone_info.name
                )
                for instance in client.list(request=request):
                    instances.append(_format_gce_instance(instance, zone_info.name))

        return {
            'success': True,
            'project': proj_id,
            'count': len(instances),
            'instances': instances
        }
    except Exception as e:
        logger.error(f"Error listing GCE instances: {str(e)}")
        return {'success': False, 'error': str(e)}


def _format_gce_instance(instance, zone: str) -> Dict[str, Any]:
    """Format GCE instance data."""
    return {
        'name': instance.name,
        'id': instance.id,
        'zone': zone,
        'machine_type': instance.machine_type.split('/')[-1],
        'status': instance.status,
        'internal_ip': instance.network_interfaces[0].network_i_p if instance.network_interfaces else None,
        'external_ip': instance.network_interfaces[0].access_configs[0].nat_i_p if instance.network_interfaces and instance.network_interfaces[0].access_configs else None,
        'tags': list(instance.tags.items) if instance.tags else [],
        'labels': dict(instance.labels) if instance.labels else {}
    }


def manage_compute_instance(
    instance_name: str,
    zone: str,
    action: str,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Manage GCE instance (start, stop, reset).

    Args:
        instance_name: Instance name
        zone: GCP zone
        action: Action to perform (start, stop, reset)
        project_id: GCP project ID

    Returns:
        Dictionary with operation result
    """
    try:
        from google.cloud import compute_v1

        client, proj_id = _get_gcp_client('compute', project_id)

        if action == 'start':
            request = compute_v1.StartInstanceRequest(
                project=proj_id,
                zone=zone,
                instance=instance_name
            )
            operation = client.start(request=request)
        elif action == 'stop':
            request = compute_v1.StopInstanceRequest(
                project=proj_id,
                zone=zone,
                instance=instance_name
            )
            operation = client.stop(request=request)
        elif action == 'reset':
            request = compute_v1.ResetInstanceRequest(
                project=proj_id,
                zone=zone,
                instance=instance_name
            )
            operation = client.reset(request=request)
        else:
            return {'success': False, 'error': f'Invalid action: {action}'}

        return {
            'success': True,
            'message': f'Instance {instance_name} {action} operation initiated',
            'project': proj_id,
            'zone': zone,
            'instance': instance_name,
            'action': action
        }
    except Exception as e:
        logger.error(f"Error managing GCE instance: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_storage_buckets(project_id: Optional[str] = None) -> Dict[str, Any]:
    """
    List Google Cloud Storage buckets.

    Args:
        project_id: GCP project ID

    Returns:
        Dictionary with bucket information
    """
    try:
        client, proj_id = _get_gcp_client('storage', project_id)

        buckets = []
        for bucket in client.list_buckets():
            buckets.append({
                'name': bucket.name,
                'location': bucket.location,
                'storage_class': bucket.storage_class,
                'time_created': bucket.time_created.isoformat() if bucket.time_created else None,
                'size_bytes': bucket.size if hasattr(bucket, 'size') else None,
                'labels': dict(bucket.labels) if bucket.labels else {}
            })

        return {
            'success': True,
            'project': proj_id,
            'count': len(buckets),
            'buckets': buckets
        }
    except Exception as e:
        logger.error(f"Error listing GCS buckets: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_gke_clusters(
    project_id: Optional[str] = None,
    location: str = '-'
) -> Dict[str, Any]:
    """
    List Google Kubernetes Engine clusters.

    Args:
        project_id: GCP project ID
        location: GCP location (zone or region, use '-' for all)

    Returns:
        Dictionary with cluster information
    """
    try:
        from google.cloud import container_v1

        client, proj_id = _get_gcp_client('container', project_id)

        parent = f"projects/{proj_id}/locations/{location}"
        request = container_v1.ListClustersRequest(parent=parent)

        response = client.list_clusters(request=request)

        clusters = []
        for cluster in response.clusters:
            clusters.append({
                'name': cluster.name,
                'location': cluster.location,
                'status': container_v1.Cluster.Status(cluster.status).name,
                'node_count': cluster.current_node_count,
                'master_version': cluster.current_master_version,
                'node_version': cluster.current_node_version,
                'endpoint': cluster.endpoint,
                'network': cluster.network,
                'subnetwork': cluster.subnetwork,
                'labels': dict(cluster.resource_labels) if cluster.resource_labels else {}
            })

        return {
            'success': True,
            'project': proj_id,
            'count': len(clusters),
            'clusters': clusters
        }
    except Exception as e:
        logger.error(f"Error listing GKE clusters: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_cloud_sql_instances(project_id: Optional[str] = None) -> Dict[str, Any]:
    """
    List Cloud SQL instances.

    Args:
        project_id: GCP project ID

    Returns:
        Dictionary with SQL instance information
    """
    try:
        from google.cloud import sql_v1

        client, proj_id = _get_gcp_client('sql', project_id)

        request = sql_v1.ListRequest(project=proj_id)
        response = client.list(request=request)

        instances = []
        for instance in response.items:
            instances.append({
                'name': instance.name,
                'database_version': instance.database_version,
                'state': sql_v1.DatabaseInstance.SqlInstanceState(instance.state).name,
                'region': instance.region,
                'tier': instance.settings.tier if instance.settings else None,
                'ip_addresses': [
                    {'type': ip.type_.name, 'ip_address': ip.ip_address}
                    for ip in instance.ip_addresses
                ] if instance.ip_addresses else [],
                'connection_name': instance.connection_name
            })

        return {
            'success': True,
            'project': proj_id,
            'count': len(instances),
            'sql_instances': instances
        }
    except Exception as e:
        logger.error(f"Error listing Cloud SQL instances: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_gcp_metrics(
    project_id: Optional[str] = None,
    metric_type: str = 'compute.googleapis.com/instance/cpu/utilization',
    resource_type: str = 'gce_instance',
    hours: int = 1
) -> Dict[str, Any]:
    """
    Get GCP metrics from Cloud Monitoring.

    Args:
        project_id: GCP project ID
        metric_type: Metric type to query
        resource_type: Resource type
        hours: Number of hours of historical data

    Returns:
        Dictionary with metrics data
    """
    try:
        from google.cloud import monitoring_v3
        from google.protobuf import duration_pb2
        from datetime import datetime, timedelta

        client, proj_id = _get_gcp_client('monitoring', project_id)

        project_name = f"projects/{proj_id}"

        # Set time interval
        now = datetime.utcnow()
        interval = monitoring_v3.TimeInterval(
            {
                "end_time": {"seconds": int(now.timestamp())},
                "start_time": {"seconds": int((now - timedelta(hours=hours)).timestamp())},
            }
        )

        # Build request
        request = monitoring_v3.ListTimeSeriesRequest(
            name=project_name,
            filter=f'metric.type="{metric_type}" AND resource.type="{resource_type}"',
            interval=interval,
            view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
        )

        results = client.list_time_series(request=request)

        metrics_data = []
        for result in results:
            points = []
            for point in result.points:
                points.append({
                    'timestamp': point.interval.end_time.isoformat(),
                    'value': point.value.double_value or point.value.int64_value
                })

            metrics_data.append({
                'metric': result.metric.type,
                'resource': result.resource.type,
                'labels': dict(result.metric.labels),
                'resource_labels': dict(result.resource.labels),
                'points': points
            })

        return {
            'success': True,
            'project': proj_id,
            'metric_type': metric_type,
            'count': len(metrics_data),
            'metrics': metrics_data
        }
    except Exception as e:
        logger.error(f"Error getting GCP metrics: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_cloud_functions(project_id: Optional[str] = None, location: str = '-') -> Dict[str, Any]:
    """
    List Cloud Functions.

    Args:
        project_id: GCP project ID
        location: GCP location (use '-' for all locations)

    Returns:
        Dictionary with Cloud Functions information
    """
    try:
        from google.cloud import functions_v1

        client = functions_v1.CloudFunctionsServiceClient()
        _, proj_id = _get_gcp_client('storage', project_id)

        parent = f"projects/{proj_id}/locations/{location}"
        request = functions_v1.ListFunctionsRequest(parent=parent)

        functions = []
        for function in client.list_functions(request=request):
            functions.append({
                'name': function.name.split('/')[-1],
                'status': functions_v1.CloudFunction.Status(function.status).name,
                'entry_point': function.entry_point,
                'runtime': function.runtime,
                'timeout': f"{function.timeout.seconds}s" if function.timeout else None,
                'available_memory_mb': function.available_memory_mb,
                'trigger': 'HTTP' if function.https_trigger else 'Event',
                'labels': dict(function.labels) if function.labels else {}
            })

        return {
            'success': True,
            'project': proj_id,
            'count': len(functions),
            'functions': functions
        }
    except Exception as e:
        logger.error(f"Error listing Cloud Functions: {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== CREATE OPERATIONS ====================


def create_compute_instance(
    instance_name: str,
    zone: str,
    machine_type: str = 'e2-medium',
    image_project: str = 'debian-cloud',
    image_family: str = 'debian-11',
    disk_size_gb: int = 10,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new Google Compute Engine instance.

    Args:
        instance_name: Name for the instance
        zone: Zone (e.g., us-central1-a, us-west1-b)
        machine_type: Machine type (e.g., e2-medium, n1-standard-1, n2-standard-2)
        image_project: Image project (default: debian-cloud)
        image_family: Image family (default: debian-11)
        disk_size_gb: Boot disk size in GB (default: 10)
        project_id: GCP project ID

    Returns:
        Dictionary with operation result
    """
    try:
        from google.cloud import compute_v1

        instances_client = compute_v1.InstancesClient()
        proj_id = _resolve_project_id(project_id)

        # Get the latest image
        images_client = compute_v1.ImagesClient()
        image = images_client.get_from_family(project=image_project, family=image_family)

        # Configure the instance
        machine_type_full = f"zones/{zone}/machineTypes/{machine_type}"

        instance = compute_v1.Instance()
        instance.name = instance_name
        instance.machine_type = machine_type_full

        # Boot disk
        disk = compute_v1.AttachedDisk()
        initialize_params = compute_v1.AttachedDiskInitializeParams()
        initialize_params.source_image = image.self_link
        initialize_params.disk_size_gb = disk_size_gb
        disk.initialize_params = initialize_params
        disk.auto_delete = True
        disk.boot = True
        instance.disks = [disk]

        # Network interface
        network_interface = compute_v1.NetworkInterface()
        network_interface.name = "global/networks/default"
        access_config = compute_v1.AccessConfig()
        access_config.name = "External NAT"
        access_config.type_ = compute_v1.AccessConfig.Type.ONE_TO_ONE_NAT.name
        network_interface.access_configs = [access_config]
        instance.network_interfaces = [network_interface]

        # Create the instance
        operation = instances_client.insert(
            project=proj_id,
            zone=zone,
            instance_resource=instance
        )

        return {
            'success': True,
            'instance_name': instance_name,
            'zone': zone,
            'machine_type': machine_type,
            'project': proj_id,
            'operation': operation.name,
            'message': f'Successfully initiated creation of instance {instance_name}. This may take a few minutes.'
        }
    except Exception as e:
        logger.error(f"Error creating GCE instance: {str(e)}")
        return {'success': False, 'error': str(e)}


def create_storage_bucket(
    bucket_name: str,
    location: str = 'US',
    storage_class: str = 'STANDARD',
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new Google Cloud Storage bucket.

    Args:
        bucket_name: Bucket name (must be globally unique)
        location: Location (e.g., US, EU, us-central1)
        storage_class: Storage class (STANDARD, NEARLINE, COLDLINE, ARCHIVE)
        project_id: GCP project ID

    Returns:
        Dictionary with operation result
    """
    try:
        from google.cloud import storage

        client, proj_id = _get_gcp_client('storage', project_id)

        bucket = client.bucket(bucket_name)
        bucket.storage_class = storage_class

        new_bucket = client.create_bucket(bucket, location=location)

        return {
            'success': True,
            'bucket_name': new_bucket.name,
            'location': new_bucket.location,
            'storage_class': new_bucket.storage_class,
            'project': proj_id,
            'self_link': new_bucket.self_link,
            'message': f'Successfully created Cloud Storage bucket {new_bucket.name}'
        }
    except Exception as e:
        logger.error(f"Error creating Cloud Storage bucket: {str(e)}")
        return {'success': False, 'error': str(e)}


def create_cloud_sql_instance(
    instance_name: str,
    database_version: str = 'MYSQL_8_0',
    tier: str = 'db-f1-micro',
    region: str = 'us-central1',
    root_password: Optional[str] = None,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new Cloud SQL instance.

    Args:
        instance_name: Instance name
        database_version: Database version (MYSQL_8_0, POSTGRES_14, SQLSERVER_2019_STANDARD)
        tier: Machine tier (db-f1-micro, db-n1-standard-1, db-n1-standard-2)
        region: Region (e.g., us-central1, us-east1, europe-west1)
        root_password: Root user password (optional, will be auto-generated if not provided)
        project_id: GCP project ID

    Returns:
        Dictionary with operation result
    """
    try:
        from googleapiclient import discovery
        from google.oauth2 import service_account
        import google.auth

        proj_id = _resolve_project_id(project_id)

        # Try per-user credentials, fall back to default
        user_creds, _ = _get_user_gcp_credentials()
        credentials = user_creds if user_creds else google.auth.default()[0]
        sqladmin = discovery.build('sqladmin', 'v1beta4', credentials=credentials)

        instance_body = {
            'name': instance_name,
            'region': region,
            'databaseVersion': database_version,
            'settings': {
                'tier': tier,
                'backupConfiguration': {
                    'enabled': True,
                    'startTime': '03:00'
                },
                'ipConfiguration': {
                    'ipv4Enabled': True
                }
            }
        }

        if root_password:
            instance_body['rootPassword'] = root_password

        operation = sqladmin.instances().insert(
            project=proj_id,
            body=instance_body
        ).execute()

        return {
            'success': True,
            'instance_name': instance_name,
            'database_version': database_version,
            'tier': tier,
            'region': region,
            'project': proj_id,
            'operation': operation.get('name'),
            'message': f'Successfully initiated creation of Cloud SQL instance {instance_name}. This may take several minutes.'
        }
    except Exception as e:
        logger.error(f"Error creating Cloud SQL instance: {str(e)}")
        return {'success': False, 'error': str(e)}


def delete_compute_instance(
    instance_name: str,
    zone: str,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Delete a Google Compute Engine instance.

    Args:
        instance_name: Instance name
        zone: Zone where instance is located
        project_id: GCP project ID

    Returns:
        Dictionary with operation result
    """
    try:
        from google.cloud import compute_v1

        instances_client = compute_v1.InstancesClient()
        proj_id = _resolve_project_id(project_id)

        operation = instances_client.delete(
            project=proj_id,
            zone=zone,
            instance=instance_name
        )

        return {
            'success': True,
            'instance_name': instance_name,
            'zone': zone,
            'project': proj_id,
            'operation': operation.name,
            'message': f'Successfully deleted instance {instance_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting GCE instance: {str(e)}")
        return {'success': False, 'error': str(e)}


def delete_storage_bucket(
    bucket_name: str,
    force: bool = False,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Delete a Google Cloud Storage bucket.

    Args:
        bucket_name: Bucket name
        force: If True, delete all objects first
        project_id: GCP project ID

    Returns:
        Dictionary with operation result
    """
    try:
        from google.cloud import storage

        client, proj_id = _get_gcp_client('storage', project_id)

        bucket = client.bucket(bucket_name)

        if force:
            # Delete all blobs
            blobs = bucket.list_blobs()
            for blob in blobs:
                blob.delete()

        bucket.delete()

        return {
            'success': True,
            'bucket_name': bucket_name,
            'project': proj_id,
            'message': f'Successfully deleted Cloud Storage bucket {bucket_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting Cloud Storage bucket: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_cloud_run_services(
    project_id: Optional[str] = None,
    region: str = 'us-central1'
) -> Dict[str, Any]:
    """
    List Cloud Run services.

    Args:
        project_id: GCP project ID
        region: GCP region (default: us-central1)

    Returns:
        Dictionary with Cloud Run services information
    """
    try:
        from google.cloud import run_v2

        client = run_v2.ServicesClient()
        proj_id = _resolve_project_id(project_id)

        parent = f"projects/{proj_id}/locations/{region}"
        request = run_v2.ListServicesRequest(parent=parent)

        services = []
        for service in client.list_services(request=request):
            services.append({
                'name': service.name.split('/')[-1],
                'uri': service.uri,
                'description': service.description,
                'labels': dict(service.labels) if service.labels else {},
                'generation': service.generation,
                'conditions': [
                    {'type': c.type_, 'status': c.state.name}
                    for c in service.conditions
                ] if service.conditions else []
            })

        return {
            'success': True,
            'project': proj_id,
            'region': region,
            'count': len(services),
            'services': services
        }
    except Exception as e:
        logger.error(f"Error listing Cloud Run services: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_pubsub_topics(project_id: Optional[str] = None) -> Dict[str, Any]:
    """
    List Pub/Sub topics.

    Args:
        project_id: GCP project ID

    Returns:
        Dictionary with Pub/Sub topics information
    """
    try:
        from google.cloud import pubsub_v1

        publisher = pubsub_v1.PublisherClient()
        proj_id = _resolve_project_id(project_id)

        project_path = f"projects/{proj_id}"

        topics = []
        for topic in publisher.list_topics(request={"project": project_path}):
            topics.append({
                'name': topic.name.split('/')[-1],
                'full_name': topic.name,
                'labels': dict(topic.labels) if topic.labels else {}
            })

        return {
            'success': True,
            'project': proj_id,
            'count': len(topics),
            'topics': topics
        }
    except Exception as e:
        logger.error(f"Error listing Pub/Sub topics: {str(e)}")
        return {'success': False, 'error': str(e)}


def publish_pubsub_message(
    topic_name: str,
    message_data: str,
    project_id: Optional[str] = None,
    attributes: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Publish a message to a Pub/Sub topic.

    Args:
        topic_name: Topic name
        message_data: Message data to publish
        project_id: GCP project ID
        attributes: Optional message attributes

    Returns:
        Dictionary with publish result
    """
    try:
        from google.cloud import pubsub_v1

        publisher = pubsub_v1.PublisherClient()
        proj_id = _resolve_project_id(project_id)

        topic_path = publisher.topic_path(proj_id, topic_name)

        # Encode message data
        data = message_data.encode('utf-8')

        # Publish message
        if attributes:
            future = publisher.publish(topic_path, data, **attributes)
        else:
            future = publisher.publish(topic_path, data)

        message_id = future.result()

        return {
            'success': True,
            'project': proj_id,
            'topic': topic_name,
            'message_id': message_id,
            'message': f'Message published to topic {topic_name} with ID: {message_id}'
        }
    except Exception as e:
        logger.error(f"Error publishing Pub/Sub message: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_bigquery_datasets(project_id: Optional[str] = None) -> Dict[str, Any]:
    """
    List BigQuery datasets.

    Args:
        project_id: GCP project ID

    Returns:
        Dictionary with BigQuery datasets information
    """
    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=_resolve_project_id(project_id))

        datasets = []
        for dataset in client.list_datasets():
            datasets.append({
                'dataset_id': dataset.dataset_id,
                'full_id': dataset.full_dataset_id,
                'project': dataset.project,
                'location': dataset.location if hasattr(dataset, 'location') else None,
                'labels': dict(dataset.labels) if hasattr(dataset, 'labels') and dataset.labels else {}
            })

        return {
            'success': True,
            'project': client.project,
            'count': len(datasets),
            'datasets': datasets
        }
    except Exception as e:
        logger.error(f"Error listing BigQuery datasets: {str(e)}")
        return {'success': False, 'error': str(e)}


def query_bigquery(
    query: str,
    project_id: Optional[str] = None,
    max_results: int = 100
) -> Dict[str, Any]:
    """
    Execute a BigQuery SQL query.

    Args:
        query: SQL query to execute
        project_id: GCP project ID
        max_results: Maximum number of results to return

    Returns:
        Dictionary with query results
    """
    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=_resolve_project_id(project_id))

        query_job = client.query(query)
        results = query_job.result(max_results=max_results)

        # Convert results to list of dicts
        rows = []
        for row in results:
            rows.append(dict(row))

        return {
            'success': True,
            'project': client.project,
            'total_rows': results.total_rows,
            'rows_returned': len(rows),
            'rows': rows,
            'query': query
        }
    except Exception as e:
        logger.error(f"Error executing BigQuery query: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_secrets(project_id: Optional[str] = None) -> Dict[str, Any]:
    """
    List Secret Manager secrets.

    Args:
        project_id: GCP project ID

    Returns:
        Dictionary with secrets information
    """
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        proj_id = _resolve_project_id(project_id)

        parent = f"projects/{proj_id}"

        secrets = []
        for secret in client.list_secrets(request={"parent": parent}):
            secrets.append({
                'name': secret.name.split('/')[-1],
                'full_name': secret.name,
                'labels': dict(secret.labels) if secret.labels else {},
                'create_time': secret.create_time.isoformat() if secret.create_time else None
            })

        return {
            'success': True,
            'project': proj_id,
            'count': len(secrets),
            'secrets': secrets
        }
    except Exception as e:
        logger.error(f"Error listing Secret Manager secrets: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_secret_value(
    secret_name: str,
    version: str = 'latest',
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get the value of a secret from Secret Manager.

    Args:
        secret_name: Secret name
        version: Secret version (default: 'latest')
        project_id: GCP project ID

    Returns:
        Dictionary with secret value
    """
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        proj_id = _resolve_project_id(project_id)

        name = f"projects/{proj_id}/secrets/{secret_name}/versions/{version}"
        response = client.access_secret_version(request={"name": name})

        payload = response.payload.data.decode('UTF-8')

        return {
            'success': True,
            'project': proj_id,
            'secret_name': secret_name,
            'version': version,
            'value': payload
        }
    except Exception as e:
        logger.error(f"Error getting secret value: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_cloud_logs(
    project_id: Optional[str] = None,
    filter_query: Optional[str] = None,
    max_entries: int = 50
) -> Dict[str, Any]:
    """
    List Cloud Logging entries.

    Args:
        project_id: GCP project ID
        filter_query: Optional filter query (e.g., 'severity>=ERROR')
        max_entries: Maximum number of log entries to return

    Returns:
        Dictionary with log entries
    """
    try:
        from google.cloud import logging

        client = logging.Client(project=_resolve_project_id(project_id))

        if filter_query:
            iterator = client.list_entries(filter_=filter_query, max_results=max_entries)
        else:
            iterator = client.list_entries(max_results=max_entries)

        entries = []
        for entry in iterator:
            entries.append({
                'timestamp': entry.timestamp.isoformat() if entry.timestamp else None,
                'severity': entry.severity,
                'log_name': entry.log_name,
                'resource_type': entry.resource.type if entry.resource else None,
                'payload': str(entry.payload),
                'labels': dict(entry.labels) if entry.labels else {}
            })

        return {
            'success': True,
            'project': client.project,
            'count': len(entries),
            'filter': filter_query,
            'entries': entries
        }
    except Exception as e:
        logger.error(f"Error listing Cloud Logging entries: {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== CLOUD SQL LIFECYCLE ====================


def delete_cloud_sql_instance(instance_name: str, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Delete a Cloud SQL instance."""
    try:
        from google.cloud.sql_v1 import SqlInstancesServiceClient
        from google.cloud.sql_v1.types import SqlInstancesDeleteRequest

        proj_id = _resolve_project_id(project_id)
        client = SqlInstancesServiceClient()
        operation = client.delete(request=SqlInstancesDeleteRequest(project=proj_id, instance=instance_name))
        return {
            'success': True, 'instance_name': instance_name, 'project': proj_id,
            'message': f'Successfully deleted Cloud SQL instance {instance_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting Cloud SQL instance: {str(e)}")
        return {'success': False, 'error': str(e)}


def restart_cloud_sql_instance(instance_name: str, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Restart a Cloud SQL instance."""
    try:
        from google.cloud.sql_v1 import SqlInstancesServiceClient
        from google.cloud.sql_v1.types import SqlInstancesRestartRequest

        proj_id = _resolve_project_id(project_id)
        client = SqlInstancesServiceClient()
        operation = client.restart(request=SqlInstancesRestartRequest(project=proj_id, instance=instance_name))
        return {
            'success': True, 'instance_name': instance_name, 'project': proj_id,
            'message': f'Successfully restarted Cloud SQL instance {instance_name}'
        }
    except Exception as e:
        logger.error(f"Error restarting Cloud SQL instance: {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== PUB/SUB MANAGEMENT ====================


def create_pubsub_topic(topic_name: str, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Create a Pub/Sub topic."""
    try:
        from google.cloud import pubsub_v1

        proj_id = _resolve_project_id(project_id)
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(proj_id, topic_name)
        topic = publisher.create_topic(request={'name': topic_path})
        return {
            'success': True, 'topic_name': topic.name, 'project': proj_id,
            'message': f'Successfully created Pub/Sub topic {topic_name}'
        }
    except Exception as e:
        logger.error(f"Error creating Pub/Sub topic: {str(e)}")
        return {'success': False, 'error': str(e)}


def delete_pubsub_topic(topic_name: str, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Delete a Pub/Sub topic."""
    try:
        from google.cloud import pubsub_v1

        proj_id = _resolve_project_id(project_id)
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(proj_id, topic_name)
        publisher.delete_topic(request={'topic': topic_path})
        return {
            'success': True, 'topic_name': topic_name, 'project': proj_id,
            'message': f'Successfully deleted Pub/Sub topic {topic_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting Pub/Sub topic: {str(e)}")
        return {'success': False, 'error': str(e)}


def create_pubsub_subscription(
    subscription_name: str,
    topic_name: str,
    ack_deadline_seconds: int = 10,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create a Pub/Sub subscription."""
    try:
        from google.cloud import pubsub_v1

        proj_id = _resolve_project_id(project_id)
        subscriber = pubsub_v1.SubscriberClient()
        topic_path = subscriber.topic_path(proj_id, topic_name)
        subscription_path = subscriber.subscription_path(proj_id, subscription_name)

        subscription = subscriber.create_subscription(request={
            'name': subscription_path,
            'topic': topic_path,
            'ack_deadline_seconds': ack_deadline_seconds,
        })
        return {
            'success': True, 'subscription_name': subscription.name,
            'topic': subscription.topic, 'project': proj_id,
            'message': f'Successfully created subscription {subscription_name} on topic {topic_name}'
        }
    except Exception as e:
        logger.error(f"Error creating Pub/Sub subscription: {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== SECRET MANAGER ====================


def create_gcp_secret(
    secret_id: str,
    secret_value: Optional[str] = None,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create a secret in Secret Manager, optionally with an initial value."""
    try:
        from google.cloud import secretmanager_v1

        proj_id = _resolve_project_id(project_id)
        client = secretmanager_v1.SecretManagerServiceClient()
        parent = f'projects/{proj_id}'

        secret = client.create_secret(request={
            'parent': parent,
            'secret_id': secret_id,
            'secret': {'replication': {'automatic': {}}},
        })

        version = None
        if secret_value:
            ver = client.add_secret_version(request={
                'parent': secret.name,
                'payload': {'data': secret_value.encode('UTF-8')},
            })
            version = ver.name

        return {
            'success': True, 'secret_name': secret.name, 'project': proj_id,
            'version': version,
            'message': f'Successfully created secret {secret_id}'
        }
    except Exception as e:
        logger.error(f"Error creating secret: {str(e)}")
        return {'success': False, 'error': str(e)}


def delete_gcp_secret(secret_id: str, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Delete a secret from Secret Manager."""
    try:
        from google.cloud import secretmanager_v1

        proj_id = _resolve_project_id(project_id)
        client = secretmanager_v1.SecretManagerServiceClient()
        name = f'projects/{proj_id}/secrets/{secret_id}'
        client.delete_secret(request={'name': name})
        return {
            'success': True, 'secret_id': secret_id, 'project': proj_id,
            'message': f'Successfully deleted secret {secret_id}'
        }
    except Exception as e:
        logger.error(f"Error deleting secret: {str(e)}")
        return {'success': False, 'error': str(e)}


def add_secret_version(
    secret_id: str,
    secret_value: str,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Add a new version to an existing secret."""
    try:
        from google.cloud import secretmanager_v1

        proj_id = _resolve_project_id(project_id)
        client = secretmanager_v1.SecretManagerServiceClient()
        parent = f'projects/{proj_id}/secrets/{secret_id}'

        version = client.add_secret_version(request={
            'parent': parent,
            'payload': {'data': secret_value.encode('UTF-8')},
        })
        return {
            'success': True, 'version_name': version.name, 'secret_id': secret_id,
            'project': proj_id,
            'message': f'Successfully added new version to secret {secret_id}'
        }
    except Exception as e:
        logger.error(f"Error adding secret version: {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== CLOUD RUN ====================


def deploy_cloud_run_service(
    service_name: str,
    image: str,
    region: str = 'us-central1',
    port: int = 8080,
    memory: str = '512Mi',
    cpu: str = '1',
    max_instances: int = 10,
    env_vars: Optional[Dict[str, str]] = None,
    allow_unauthenticated: bool = False,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Deploy a Cloud Run service."""
    try:
        from google.cloud import run_v2

        proj_id = _resolve_project_id(project_id)
        client = run_v2.ServicesClient()
        parent = f'projects/{proj_id}/locations/{region}'

        env_list = []
        if env_vars:
            env_list = [run_v2.EnvVar(name=k, value=v) for k, v in env_vars.items()]

        container = run_v2.Container(
            image=image,
            ports=[run_v2.ContainerPort(container_port=port)],
            resources=run_v2.ResourceRequirements(
                limits={'memory': memory, 'cpu': cpu}
            ),
            env=env_list or None,
        )

        service = run_v2.Service(
            template=run_v2.RevisionTemplate(
                containers=[container],
                scaling=run_v2.RevisionScaling(max_instance_count=max_instances),
            ),
        )

        operation = client.create_service(request={
            'parent': parent,
            'service': service,
            'service_id': service_name,
        })
        result = operation.result()

        return {
            'success': True, 'service_name': result.name, 'uri': result.uri,
            'project': proj_id, 'region': region, 'image': image,
            'message': f'Successfully deployed Cloud Run service {service_name}'
        }
    except Exception as e:
        logger.error(f"Error deploying Cloud Run service: {str(e)}")
        return {'success': False, 'error': str(e)}


def delete_cloud_run_service(
    service_name: str,
    region: str = 'us-central1',
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a Cloud Run service."""
    try:
        from google.cloud import run_v2

        proj_id = _resolve_project_id(project_id)
        client = run_v2.ServicesClient()
        name = f'projects/{proj_id}/locations/{region}/services/{service_name}'
        operation = client.delete_service(request={'name': name})
        operation.result()
        return {
            'success': True, 'service_name': service_name, 'project': proj_id, 'region': region,
            'message': f'Successfully deleted Cloud Run service {service_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting Cloud Run service: {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== GKE CLUSTER MANAGEMENT ====================


def resize_gke_cluster(
    cluster_name: str,
    node_pool_name: str,
    node_count: int,
    zone: str,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Resize a GKE cluster node pool."""
    try:
        from google.cloud import container_v1

        proj_id = _resolve_project_id(project_id)
        client = container_v1.ClusterManagerClient()
        name = f'projects/{proj_id}/locations/{zone}/clusters/{cluster_name}/nodePools/{node_pool_name}'

        operation = client.set_node_pool_size(request={
            'name': name,
            'node_count': node_count,
        })
        return {
            'success': True, 'cluster': cluster_name, 'node_pool': node_pool_name,
            'node_count': node_count, 'zone': zone, 'project': proj_id,
            'operation': operation.name,
            'message': f'Successfully resized {node_pool_name} to {node_count} nodes'
        }
    except Exception as e:
        logger.error(f"Error resizing GKE cluster: {str(e)}")
        return {'success': False, 'error': str(e)}


def delete_gke_cluster(
    cluster_name: str,
    zone: str,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a GKE cluster."""
    try:
        from google.cloud import container_v1

        proj_id = _resolve_project_id(project_id)
        client = container_v1.ClusterManagerClient()
        name = f'projects/{proj_id}/locations/{zone}/clusters/{cluster_name}'

        operation = client.delete_cluster(request={'name': name})
        return {
            'success': True, 'cluster': cluster_name, 'zone': zone, 'project': proj_id,
            'operation': operation.name,
            'message': f'Successfully initiated deletion of GKE cluster {cluster_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting GKE cluster: {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== VPC FIREWALL RULES ====================


def list_firewall_rules(project_id: Optional[str] = None) -> Dict[str, Any]:
    """List GCP VPC firewall rules."""
    try:
        from google.cloud import compute_v1

        proj_id = _resolve_project_id(project_id)
        client = compute_v1.FirewallsClient()
        request = compute_v1.ListFirewallsRequest(project=proj_id)

        rules = []
        for rule in client.list(request=request):
            rules.append({
                'name': rule.name,
                'network': rule.network.split('/')[-1] if rule.network else None,
                'direction': rule.direction,
                'priority': rule.priority,
                'source_ranges': list(rule.source_ranges) if rule.source_ranges else [],
                'target_tags': list(rule.target_tags) if rule.target_tags else [],
                'allowed': [{'protocol': a.I_p_protocol, 'ports': list(a.ports)} for a in rule.allowed] if rule.allowed else [],
                'denied': [{'protocol': d.I_p_protocol, 'ports': list(d.ports)} for d in rule.denied] if rule.denied else [],
                'disabled': rule.disabled,
            })

        return {'success': True, 'count': len(rules), 'firewall_rules': rules, 'project': proj_id}
    except Exception as e:
        logger.error(f"Error listing firewall rules: {str(e)}")
        return {'success': False, 'error': str(e)}


def create_firewall_rule(
    rule_name: str,
    network: str = 'default',
    direction: str = 'INGRESS',
    priority: int = 1000,
    protocol: str = 'tcp',
    ports: Optional[List[str]] = None,
    source_ranges: Optional[List[str]] = None,
    target_tags: Optional[List[str]] = None,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create a GCP VPC firewall rule."""
    try:
        from google.cloud import compute_v1

        proj_id = _resolve_project_id(project_id)
        client = compute_v1.FirewallsClient()

        firewall = compute_v1.Firewall(
            name=rule_name,
            network=f'projects/{proj_id}/global/networks/{network}',
            direction=direction,
            priority=priority,
            allowed=[compute_v1.Allowed(I_p_protocol=protocol, ports=ports or ['80'])],
            source_ranges=source_ranges or ['0.0.0.0/0'],
            target_tags=target_tags or [],
        )

        operation = client.insert(project=proj_id, firewall_resource=firewall)
        return {
            'success': True, 'rule_name': rule_name, 'network': network,
            'direction': direction, 'protocol': protocol, 'ports': ports or ['80'],
            'project': proj_id,
            'message': f'Successfully created firewall rule {rule_name}'
        }
    except Exception as e:
        logger.error(f"Error creating firewall rule: {str(e)}")
        return {'success': False, 'error': str(e)}


def delete_firewall_rule(rule_name: str, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Delete a GCP VPC firewall rule."""
    try:
        from google.cloud import compute_v1

        proj_id = _resolve_project_id(project_id)
        client = compute_v1.FirewallsClient()
        operation = client.delete(project=proj_id, firewall=rule_name)
        return {
            'success': True, 'rule_name': rule_name, 'project': proj_id,
            'message': f'Successfully deleted firewall rule {rule_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting firewall rule: {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== BIGQUERY ====================


def create_bigquery_dataset(
    dataset_id: str,
    location: str = 'US',
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create a BigQuery dataset."""
    try:
        from google.cloud import bigquery

        proj_id = _resolve_project_id(project_id)
        client = bigquery.Client(project=proj_id)

        dataset_ref = bigquery.DatasetReference(proj_id, dataset_id)
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = location

        result = client.create_dataset(dataset)
        return {
            'success': True, 'dataset_id': result.dataset_id,
            'location': result.location, 'project': result.project,
            'message': f'Successfully created BigQuery dataset {dataset_id}'
        }
    except Exception as e:
        logger.error(f"Error creating BigQuery dataset: {str(e)}")
        return {'success': False, 'error': str(e)}


def delete_bigquery_dataset(
    dataset_id: str,
    delete_contents: bool = False,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a BigQuery dataset."""
    try:
        from google.cloud import bigquery

        proj_id = _resolve_project_id(project_id)
        client = bigquery.Client(project=proj_id)
        client.delete_dataset(dataset_id, delete_contents=delete_contents)
        return {
            'success': True, 'dataset_id': dataset_id, 'project': proj_id,
            'message': f'Successfully deleted BigQuery dataset {dataset_id}'
        }
    except Exception as e:
        logger.error(f"Error deleting BigQuery dataset: {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== CLOUD FUNCTIONS ====================


def delete_cloud_function(
    function_name: str,
    region: str = 'us-central1',
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a Cloud Function."""
    try:
        from google.cloud.functions_v2 import FunctionServiceClient

        proj_id = _resolve_project_id(project_id)
        client = FunctionServiceClient()
        name = f'projects/{proj_id}/locations/{region}/functions/{function_name}'
        operation = client.delete_function(request={'name': name})
        operation.result()
        return {
            'success': True, 'function_name': function_name, 'region': region, 'project': proj_id,
            'message': f'Successfully deleted Cloud Function {function_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting Cloud Function: {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== COMPUTE SNAPSHOTS ====================


def create_disk_snapshot(
    disk_name: str,
    snapshot_name: str,
    zone: str,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create a snapshot of a Compute Engine disk."""
    try:
        from google.cloud import compute_v1

        proj_id = _resolve_project_id(project_id)
        snapshots_client = compute_v1.SnapshotsClient()
        disks_client = compute_v1.DisksClient()

        snapshot = compute_v1.Snapshot(
            name=snapshot_name,
            source_disk=f'projects/{proj_id}/zones/{zone}/disks/{disk_name}',
        )

        operation = snapshots_client.insert(project=proj_id, snapshot_resource=snapshot)
        return {
            'success': True, 'snapshot_name': snapshot_name, 'disk_name': disk_name,
            'zone': zone, 'project': proj_id,
            'message': f'Successfully created snapshot {snapshot_name} of disk {disk_name}'
        }
    except Exception as e:
        logger.error(f"Error creating disk snapshot: {str(e)}")
        return {'success': False, 'error': str(e)}


def delete_disk_snapshot(snapshot_name: str, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Delete a Compute Engine disk snapshot."""
    try:
        from google.cloud import compute_v1

        proj_id = _resolve_project_id(project_id)
        client = compute_v1.SnapshotsClient()
        operation = client.delete(project=proj_id, snapshot=snapshot_name)
        return {
            'success': True, 'snapshot_name': snapshot_name, 'project': proj_id,
            'message': f'Successfully deleted snapshot {snapshot_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting disk snapshot: {str(e)}")
        return {'success': False, 'error': str(e)}


_GCP_READ_METHODS = ('list', 'get', 'aggregated_list', 'list_all', 'list_instances',
                     'list_by_project', 'list_available', 'read', 'fetch', 'search')


def _is_gcp_read(method: str) -> bool:
    return any(method.lower().startswith(p) for p in _GCP_READ_METHODS)


def gcp_api_read(
    api_name: str,
    api_version: str,
    resource_path: str,
    method: str,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Call ANY GCP read-only API operation via google-api-python-client when no dedicated tool exists.

    Examples:
      gcp_api_read('cloudfunctions','v2','projects.locations.functions','list',{'parent':'projects/my-proj/locations/-'})
      gcp_api_read('dns','v1','managedZones','list',{'project':'my-proj'})
      gcp_api_read('redis','v1','projects.locations.instances','list',{'parent':'projects/my-proj/locations/-'})
    """
    if not _is_gcp_read(method):
        return {'success': False, 'error': f'"{method}" does not look like a read operation. Use gcp_api_write for create/update/delete.'}
    try:
        from googleapiclient import discovery as gcp_discovery
        credentials, project_id = _get_user_gcp_credentials()
        service = gcp_discovery.build(api_name, api_version, credentials=credentials)
        # Navigate dot-separated resource path: "projects.locations.functions" → service.projects().locations().functions()
        obj = service
        for part in resource_path.split('.'):
            obj = getattr(obj, part)()
        all_params = {'project': project_id, **(params or {})}
        result = obj.__getattribute__(method)(**all_params).execute()
        return {'success': True, 'api': f'{api_name}/{api_version}', 'resource': resource_path,
                'method': method, 'result': result}
    except Exception as e:
        logger.error(f"gcp_api_read error ({api_name}.{resource_path}.{method}): {str(e)}")
        return {'success': False, 'error': str(e)}


def gcp_api_write(
    api_name: str,
    api_version: str,
    resource_path: str,
    method: str,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Call ANY GCP write API operation via google-api-python-client when no dedicated tool exists.
    Requires user confirmation. Always confirm operation and params before calling.

    Examples:
      gcp_api_write('compute','v1','instances','delete',{'project':'my-proj','zone':'us-central1-a','instance':'my-vm'})
      gcp_api_write('dns','v1','resourceRecordSets','create',{'project':'my-proj','managedZone':'my-zone','body':{...}})
      gcp_api_write('redis','v1','projects.locations.instances','patch',{'name':'projects/...','body':{...},'updateMask':'memorySizeGb'})
    """
    if _is_gcp_read(method):
        return {'success': False, 'error': f'"{method}" looks like a read operation. Use gcp_api_read instead.'}
    try:
        from googleapiclient import discovery as gcp_discovery
        credentials, project_id = _get_user_gcp_credentials()
        service = gcp_discovery.build(api_name, api_version, credentials=credentials)
        obj = service
        for part in resource_path.split('.'):
            obj = getattr(obj, part)()
        all_params = {'project': project_id, **(params or {})}
        result = obj.__getattribute__(method)(**all_params).execute()
        return {'success': True, 'api': f'{api_name}/{api_version}', 'resource': resource_path,
                'method': method, 'result': result,
                'message': f'Successfully executed {api_name}.{resource_path}.{method}'}
    except Exception as e:
        logger.error(f"gcp_api_write error ({api_name}.{resource_path}.{method}): {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== TOOL REGISTRATION ====================


def get_tools() -> List[Dict[str, Any]]:
    """
    Get list of GCP tool definitions for the agent.

    Returns:
        List of tool definitions with name, description, input_schema, and handler
    """
    return [
        # Compute Engine Operations
        {
            'name': 'list_compute_instances',
            'description': 'List Google Compute Engine instances',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'},
                    'zone': {'type': 'string', 'description': 'Zone to filter instances (optional)'}
                }
            },
            'handler': list_compute_instances
        },
        {
            'name': 'manage_compute_instance',
            'description': 'Manage GCE instance (start, stop, reset)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'instance_name': {'type': 'string', 'description': 'Instance name'},
                    'zone': {'type': 'string', 'description': 'Zone where instance is located'},
                    'action': {'type': 'string', 'description': 'Action: start, stop, or reset', 'enum': ['start', 'stop', 'reset']},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['instance_name', 'zone', 'action']
            },
            'handler': manage_compute_instance
        },
        {
            'name': 'create_compute_instance',
            'description': 'Create a new Google Compute Engine instance',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'instance_name': {'type': 'string', 'description': 'Name for the instance'},
                    'zone': {'type': 'string', 'description': 'Zone (e.g., us-central1-a, us-west1-b, europe-west1-b)'},
                    'machine_type': {'type': 'string', 'description': 'Machine type (e.g., e2-medium, n1-standard-1, n2-standard-2)', 'default': 'e2-medium'},
                    'image_project': {'type': 'string', 'description': 'Image project (default: debian-cloud)', 'default': 'debian-cloud'},
                    'image_family': {'type': 'string', 'description': 'Image family (default: debian-11)', 'default': 'debian-11'},
                    'disk_size_gb': {'type': 'integer', 'description': 'Boot disk size in GB (default: 10)', 'default': 10},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['instance_name', 'zone']
            },
            'handler': create_compute_instance
        },
        {
            'name': 'delete_compute_instance',
            'description': 'Delete a Google Compute Engine instance',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'instance_name': {'type': 'string', 'description': 'Instance name'},
                    'zone': {'type': 'string', 'description': 'Zone where instance is located'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['instance_name', 'zone']
            },
            'handler': delete_compute_instance
        },
        # Cloud Storage Operations
        {
            'name': 'list_storage_buckets',
            'description': 'List Google Cloud Storage buckets',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                }
            },
            'handler': list_storage_buckets
        },
        {
            'name': 'create_storage_bucket',
            'description': 'Create a new Google Cloud Storage bucket',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name (must be globally unique)'},
                    'location': {'type': 'string', 'description': 'Location (e.g., US, EU, us-central1)', 'default': 'US'},
                    'storage_class': {'type': 'string', 'description': 'Storage class: STANDARD, NEARLINE, COLDLINE, ARCHIVE', 'default': 'STANDARD'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['bucket_name']
            },
            'handler': create_storage_bucket
        },
        {
            'name': 'delete_storage_bucket',
            'description': 'Delete a Google Cloud Storage bucket',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'force': {'type': 'boolean', 'description': 'If true, delete all objects first', 'default': False},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['bucket_name']
            },
            'handler': delete_storage_bucket
        },
        # GKE Operations
        {
            'name': 'list_gke_clusters',
            'description': 'List Google Kubernetes Engine (GKE) clusters',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'},
                    'location': {'type': 'string', 'description': 'Location to filter clusters (optional)'}
                }
            },
            'handler': list_gke_clusters
        },
        # Cloud SQL Operations
        {
            'name': 'list_cloud_sql_instances',
            'description': 'List Google Cloud SQL instances',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                }
            },
            'handler': list_cloud_sql_instances
        },
        {
            'name': 'create_cloud_sql_instance',
            'description': 'Create a new Google Cloud SQL instance',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'instance_name': {'type': 'string', 'description': 'Instance name'},
                    'database_version': {'type': 'string', 'description': 'Database version: MYSQL_8_0, POSTGRES_14, SQLSERVER_2019_STANDARD', 'default': 'MYSQL_8_0'},
                    'tier': {'type': 'string', 'description': 'Machine tier (db-f1-micro, db-n1-standard-1, db-n1-standard-2)', 'default': 'db-f1-micro'},
                    'region': {'type': 'string', 'description': 'Region (e.g., us-central1, us-east1, europe-west1)', 'default': 'us-central1'},
                    'root_password': {'type': 'string', 'description': 'Root user password (optional, auto-generated if not provided)'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['instance_name']
            },
            'handler': create_cloud_sql_instance
        },
        # Cloud Monitoring
        {
            'name': 'get_gcp_metrics',
            'description': 'Get Google Cloud Monitoring metrics',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'metric_type': {'type': 'string', 'description': 'Metric type (e.g., compute.googleapis.com/instance/cpu/utilization)'},
                    'resource_type': {'type': 'string', 'description': 'Resource type (e.g., gce_instance)'},
                    'hours': {'type': 'integer', 'description': 'Hours to look back (default: 1)', 'default': 1},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['metric_type', 'resource_type']
            },
            'handler': get_gcp_metrics
        },
        # Cloud Functions
        {
            'name': 'list_cloud_functions',
            'description': 'List Google Cloud Functions',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'},
                    'location': {'type': 'string', 'description': 'Location to filter functions (optional)'}
                }
            },
            'handler': list_cloud_functions
        },
        # Cloud Run
        {
            'name': 'list_cloud_run_services',
            'description': 'List Google Cloud Run services',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'},
                    'region': {'type': 'string', 'description': 'GCP region (default: us-central1)', 'default': 'us-central1'}
                }
            },
            'handler': list_cloud_run_services
        },
        # Pub/Sub
        {
            'name': 'list_pubsub_topics',
            'description': 'List Google Cloud Pub/Sub topics',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                }
            },
            'handler': list_pubsub_topics
        },
        {
            'name': 'publish_pubsub_message',
            'description': 'Publish a message to a Pub/Sub topic',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'topic_name': {'type': 'string', 'description': 'Topic name'},
                    'message_data': {'type': 'string', 'description': 'Message data to publish'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'},
                    'attributes': {'type': 'object', 'description': 'Optional message attributes (key-value pairs)'}
                },
                'required': ['topic_name', 'message_data']
            },
            'handler': publish_pubsub_message
        },
        # BigQuery
        {
            'name': 'list_bigquery_datasets',
            'description': 'List BigQuery datasets',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                }
            },
            'handler': list_bigquery_datasets
        },
        {
            'name': 'query_bigquery',
            'description': 'Execute a BigQuery SQL query',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string', 'description': 'SQL query to execute'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'},
                    'max_results': {'type': 'integer', 'description': 'Maximum number of results to return (default: 100)', 'default': 100}
                },
                'required': ['query']
            },
            'handler': query_bigquery
        },
        # Secret Manager
        {
            'name': 'list_secrets',
            'description': 'List Google Cloud Secret Manager secrets',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                }
            },
            'handler': list_secrets
        },
        {
            'name': 'get_secret_value',
            'description': 'Get the value of a secret from Secret Manager',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'secret_name': {'type': 'string', 'description': 'Secret name'},
                    'version': {'type': 'string', 'description': 'Secret version (default: latest)', 'default': 'latest'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['secret_name']
            },
            'handler': get_secret_value
        },
        # Cloud Logging
        {
            'name': 'list_cloud_logs',
            'description': 'List Google Cloud Logging entries',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'},
                    'filter_query': {'type': 'string', 'description': 'Optional filter query (e.g., severity>=ERROR)'},
                    'max_entries': {'type': 'integer', 'description': 'Maximum number of log entries (default: 50)', 'default': 50}
                }
            },
            'handler': list_cloud_logs
        },
        # ---- Cloud SQL Lifecycle ----
        {
            'name': 'delete_cloud_sql_instance',
            'description': 'Delete a Google Cloud SQL instance.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'instance_name': {'type': 'string', 'description': 'Cloud SQL instance name'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['instance_name']
            },
            'handler': delete_cloud_sql_instance
        },
        {
            'name': 'restart_cloud_sql_instance',
            'description': 'Restart a Google Cloud SQL instance.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'instance_name': {'type': 'string', 'description': 'Cloud SQL instance name'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['instance_name']
            },
            'handler': restart_cloud_sql_instance
        },
        # ---- Pub/Sub Management ----
        {
            'name': 'create_pubsub_topic',
            'description': 'Create a Google Cloud Pub/Sub topic.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'topic_name': {'type': 'string', 'description': 'Topic name'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['topic_name']
            },
            'handler': create_pubsub_topic
        },
        {
            'name': 'delete_pubsub_topic',
            'description': 'Delete a Google Cloud Pub/Sub topic.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'topic_name': {'type': 'string', 'description': 'Topic name'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['topic_name']
            },
            'handler': delete_pubsub_topic
        },
        {
            'name': 'create_pubsub_subscription',
            'description': 'Create a Pub/Sub subscription on a topic.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'subscription_name': {'type': 'string', 'description': 'Subscription name'},
                    'topic_name': {'type': 'string', 'description': 'Topic to subscribe to'},
                    'ack_deadline_seconds': {'type': 'integer', 'description': 'Ack deadline in seconds (default: 10)', 'default': 10},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['subscription_name', 'topic_name']
            },
            'handler': create_pubsub_subscription
        },
        # ---- Secret Manager ----
        {
            'name': 'create_gcp_secret',
            'description': 'Create a secret in Google Secret Manager, optionally with an initial value.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'secret_id': {'type': 'string', 'description': 'Secret ID'},
                    'secret_value': {'type': 'string', 'description': 'Initial secret value (optional)'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['secret_id']
            },
            'handler': create_gcp_secret
        },
        {
            'name': 'delete_gcp_secret',
            'description': 'Delete a secret from Google Secret Manager.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'secret_id': {'type': 'string', 'description': 'Secret ID'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['secret_id']
            },
            'handler': delete_gcp_secret
        },
        {
            'name': 'add_secret_version',
            'description': 'Add a new version to an existing secret in Secret Manager.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'secret_id': {'type': 'string', 'description': 'Secret ID'},
                    'secret_value': {'type': 'string', 'description': 'New secret value'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['secret_id', 'secret_value']
            },
            'handler': add_secret_version
        },
        # ---- Cloud Run ----
        {
            'name': 'deploy_cloud_run_service',
            'description': 'Deploy a Cloud Run service from a container image.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'service_name': {'type': 'string', 'description': 'Service name'},
                    'image': {'type': 'string', 'description': 'Container image (e.g., "gcr.io/project/image:tag")'},
                    'region': {'type': 'string', 'description': 'GCP region (default: us-central1)', 'default': 'us-central1'},
                    'port': {'type': 'integer', 'description': 'Container port (default: 8080)', 'default': 8080},
                    'memory': {'type': 'string', 'description': 'Memory limit (default: 512Mi)', 'default': '512Mi'},
                    'cpu': {'type': 'string', 'description': 'CPU limit (default: 1)', 'default': '1'},
                    'max_instances': {'type': 'integer', 'description': 'Max instances (default: 10)', 'default': 10},
                    'env_vars': {'type': 'object', 'description': 'Environment variables as key-value pairs'},
                    'allow_unauthenticated': {'type': 'boolean', 'description': 'Allow public access', 'default': False},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['service_name', 'image']
            },
            'handler': deploy_cloud_run_service
        },
        {
            'name': 'delete_cloud_run_service',
            'description': 'Delete a Cloud Run service.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'service_name': {'type': 'string', 'description': 'Service name'},
                    'region': {'type': 'string', 'description': 'GCP region (default: us-central1)', 'default': 'us-central1'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['service_name']
            },
            'handler': delete_cloud_run_service
        },
        # ---- GKE Cluster Management ----
        {
            'name': 'resize_gke_cluster',
            'description': 'Resize a GKE cluster node pool (scale up or down).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'GKE cluster name'},
                    'node_pool_name': {'type': 'string', 'description': 'Node pool name (e.g., "default-pool")'},
                    'node_count': {'type': 'integer', 'description': 'Desired number of nodes'},
                    'zone': {'type': 'string', 'description': 'GCP zone (e.g., "us-central1-a")'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['cluster_name', 'node_pool_name', 'node_count', 'zone']
            },
            'handler': resize_gke_cluster
        },
        {
            'name': 'delete_gke_cluster',
            'description': 'Delete a GKE cluster.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'GKE cluster name'},
                    'zone': {'type': 'string', 'description': 'GCP zone'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['cluster_name', 'zone']
            },
            'handler': delete_gke_cluster
        },
        # ---- VPC Firewall Rules ----
        {
            'name': 'list_firewall_rules',
            'description': 'List GCP VPC firewall rules.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                }
            },
            'handler': list_firewall_rules
        },
        {
            'name': 'create_firewall_rule',
            'description': 'Create a GCP VPC firewall rule.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'rule_name': {'type': 'string', 'description': 'Firewall rule name'},
                    'network': {'type': 'string', 'description': 'VPC network name (default: default)', 'default': 'default'},
                    'direction': {'type': 'string', 'enum': ['INGRESS', 'EGRESS'], 'default': 'INGRESS'},
                    'priority': {'type': 'integer', 'description': 'Priority (0-65535, lower = higher)', 'default': 1000},
                    'protocol': {'type': 'string', 'description': 'Protocol (tcp, udp, icmp)', 'default': 'tcp'},
                    'ports': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Ports to allow (e.g., ["80", "443"])'},
                    'source_ranges': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Source IP ranges (e.g., ["0.0.0.0/0"])'},
                    'target_tags': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Target instance tags'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['rule_name']
            },
            'handler': create_firewall_rule
        },
        {
            'name': 'delete_firewall_rule',
            'description': 'Delete a GCP VPC firewall rule.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'rule_name': {'type': 'string', 'description': 'Firewall rule name'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['rule_name']
            },
            'handler': delete_firewall_rule
        },
        # ---- BigQuery ----
        {
            'name': 'create_bigquery_dataset',
            'description': 'Create a BigQuery dataset.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'dataset_id': {'type': 'string', 'description': 'Dataset ID'},
                    'location': {'type': 'string', 'description': 'Location (default: US)', 'default': 'US'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['dataset_id']
            },
            'handler': create_bigquery_dataset
        },
        {
            'name': 'delete_bigquery_dataset',
            'description': 'Delete a BigQuery dataset.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'dataset_id': {'type': 'string', 'description': 'Dataset ID'},
                    'delete_contents': {'type': 'boolean', 'description': 'Delete all tables in dataset', 'default': False},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['dataset_id']
            },
            'handler': delete_bigquery_dataset
        },
        # ---- Cloud Functions ----
        {
            'name': 'delete_cloud_function',
            'description': 'Delete a Google Cloud Function.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'function_name': {'type': 'string', 'description': 'Function name'},
                    'region': {'type': 'string', 'description': 'GCP region (default: us-central1)', 'default': 'us-central1'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['function_name']
            },
            'handler': delete_cloud_function
        },
        # ---- Compute Snapshots ----
        {
            'name': 'create_disk_snapshot',
            'description': 'Create a snapshot of a Compute Engine disk for backup.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'disk_name': {'type': 'string', 'description': 'Disk name'},
                    'snapshot_name': {'type': 'string', 'description': 'Snapshot name'},
                    'zone': {'type': 'string', 'description': 'Zone where disk is located'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['disk_name', 'snapshot_name', 'zone']
            },
            'handler': create_disk_snapshot
        },
        {
            'name': 'delete_disk_snapshot',
            'description': 'Delete a Compute Engine disk snapshot.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'snapshot_name': {'type': 'string', 'description': 'Snapshot name'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['snapshot_name']
            },
            'handler': delete_disk_snapshot
        },
        {
            'name': 'gcp_api_read',
            'description': (
                'Call ANY GCP read-only API via google-api-python-client when no dedicated tool exists. '
                'Use for list/get operations across any GCP service. '
                'Examples: Cloud Functions v2 list, Cloud DNS managedZones list, '
                'Memorystore Redis instances list, Cloud Armor security policies list, '
                'Cloud Scheduler jobs list, Artifact Registry repositories list. '
                'Never use for create/update/delete — use gcp_api_write for those.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'api_name': {'type': 'string', 'description': 'GCP API name e.g. compute, dns, redis, cloudfunctions, cloudscheduler, artifactregistry'},
                    'api_version': {'type': 'string', 'description': 'API version e.g. v1, v2, v1beta1'},
                    'resource_path': {'type': 'string', 'description': 'Dot-separated resource path e.g. instances, managedZones, projects.locations.functions'},
                    'method': {'type': 'string', 'description': 'Method name e.g. list, get, aggregatedList'},
                    'params': {'type': 'object', 'description': 'API parameters (project is auto-injected)'}
                },
                'required': ['api_name', 'api_version', 'resource_path', 'method']
            },
            'handler': gcp_api_read
        },
        {
            'name': 'gcp_api_write',
            'description': (
                'Call ANY GCP write API via google-api-python-client when no dedicated tool exists. '
                'Requires user confirmation. '
                'Examples: delete a Cloud Scheduler job, create a DNS record, '
                'patch a Redis instance memory size, enable a GCP service API.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'api_name': {'type': 'string', 'description': 'GCP API name e.g. compute, dns, redis, cloudfunctions'},
                    'api_version': {'type': 'string', 'description': 'API version e.g. v1, v2'},
                    'resource_path': {'type': 'string', 'description': 'Dot-separated resource path e.g. instances, managedZones'},
                    'method': {'type': 'string', 'description': 'Method name e.g. delete, insert, patch, create'},
                    'params': {'type': 'object', 'description': 'API parameters (project is auto-injected)'}
                },
                'required': ['api_name', 'api_version', 'resource_path', 'method']
            },
            'handler': gcp_api_write
        },
    ]
