import logging
import re


logger = logging.getLogger('GrokBot')

IMAGE_URL_PATTERN = r'https?://(?:[a-zA-Z0-9\-]+\.)+[a-zA-Z]{2,}(?:/[^\s]*)?\.(?:jpg|jpeg|png|webp)(?:\?[^\s]*)?'
SUPPORTED_IMAGE_CONTENT_TYPES = {'image/jpeg', 'image/jpg', 'image/png', 'image/webp'}
SUPPORTED_DOCUMENT_EXTENSIONS = (
    '.pdf', '.txt', '.md', '.csv', '.json', '.py', '.js', '.java', '.c',
    '.cpp', '.h', '.ts', '.go', '.rs', '.rb', '.php'
)


def is_supported_image(url_or_filename):
    url = url_or_filename.lower()
    return url.endswith('.jpg') or url.endswith('.jpeg') or url.endswith('.png') or url.endswith('.webp')


def is_supported_document(filename):
    return filename.lower().endswith(SUPPORTED_DOCUMENT_EXTENSIONS)


def collect_image_urls_from_text(text, image_urls, context_label='message'):
    found_urls = re.findall(IMAGE_URL_PATTERN, text, re.IGNORECASE)
    for url in found_urls:
        if url not in image_urls:
            image_urls.append(url)
            logger.info(f'Found image URL in {context_label}: {url}')


def collect_attachment_media(message, image_urls, document_attachments=None,
                             unsupported_images=None, unsupported_docs=None,
                             context_label='message'):
    for attachment in message.attachments:
        content_type = attachment.content_type or ''
        if is_supported_image(attachment.url) or content_type in SUPPORTED_IMAGE_CONTENT_TYPES:
            if attachment.url not in image_urls:
                image_urls.append(attachment.url)
            logger.info(f'Found image attachment in {context_label}: {attachment.filename}')
        elif document_attachments is not None and is_supported_document(attachment.filename):
            document_attachments.append(attachment)
            logger.info(f'Found document attachment: {attachment.filename}')
        else:
            if not content_type.startswith('image/'):
                if unsupported_docs is not None:
                    unsupported_docs.append(attachment.filename)
                logger.warning(f'Unsupported document type: {attachment.filename} ({attachment.content_type})')
            else:
                if unsupported_images is not None:
                    unsupported_images.append(attachment.filename)
                logger.warning(f'Unsupported image type: {attachment.filename} ({attachment.content_type})')


def collect_embed_media(embeds, image_urls, context_label='message'):
    for embed in embeds:
        if embed.type in ['gifv', 'video', 'image', 'rich']:
            media_url = None

            if embed.image and embed.image.url:
                media_url = embed.image.url
            elif embed.video and embed.video.url:
                media_url = embed.video.url
            elif embed.thumbnail and embed.thumbnail.url:
                media_url = embed.thumbnail.url
            elif embed.url:
                media_url = embed.url

            if media_url and media_url not in image_urls:
                if is_supported_image(media_url):
                    image_urls.append(media_url)
                    logger.info(f'Found media in {context_label} embed ({embed.type}): {media_url}')
                else:
                    logger.warning(f'Skipping unsupported media format: {media_url}')
