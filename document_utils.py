import logging
import os
import tempfile

from xai_sdk import AsyncClient as XAIAsyncClient


logger = logging.getLogger('GrokBot')


async def upload_documents_to_grok(document_attachments):
    """Upload Discord document attachments to xAI and clean up local temp files."""
    grok_file_ids = []
    failed_uploads = []
    xai_client = None

    if not document_attachments:
        return xai_client, grok_file_ids, failed_uploads

    xai_client = XAIAsyncClient()
    for attachment in document_attachments:
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(attachment.filename)[1]) as tmp:
                tmp_path = tmp.name
                await attachment.save(tmp_path)

            uploaded_file = await xai_client.files.upload(tmp_path)
            grok_file_ids.append(uploaded_file.id)
            logger.info(f'Uploaded {attachment.filename} to Grok via SDK, file_id={uploaded_file.id}')
        except Exception as upload_error:
            logger.error(f'Error uploading {attachment.filename}: {upload_error}')
            failed_uploads.append(attachment.filename)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    return xai_client, grok_file_ids, failed_uploads


async def delete_grok_files(xai_client, file_ids):
    """Delete files previously uploaded to xAI."""
    if not xai_client:
        return

    for file_id in file_ids:
        try:
            await xai_client.files.delete(file_id)
            logger.info(f'Cleaned up uploaded file: {file_id}')
        except Exception as cleanup_error:
            logger.warning(f'Failed to cleanup file {file_id}: {cleanup_error}')
