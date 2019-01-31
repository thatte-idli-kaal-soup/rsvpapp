#!/usr/bin/env python
from cloudinary.api import resources_by_tag
from cloudinary.uploader import upload
from cloudinary.utils import cloudinary_url

TAG = "rsvpapp"
TRANSFORMS = {"standard": "800x600", "thumbnail": "200x150"}


def list_images(tag=TAG, transform=TRANSFORMS["thumbnail"]):
    """Return list of URLs for all the images """
    resources = resources_by_tag(tag)["resources"]
    data = [
        {
            "url": image_url(
                resource["public_id"], resource["format"], transform
            ),
            "resource": resource,
        }
        for resource in resources
    ]
    return data


def image_url(public_id, format_, transform=TRANSFORMS["standard"], tag=TAG):
    """Return image URL given public_id and other options."""
    width, height = map(int, transform.split("x"))
    url, options = cloudinary_url(
        public_id,
        format=format_,
        width=width,
        height=height,
        crop="fill",
        secure=True,
    )
    return url


def upload_image(path, tag=TAG, transforms=TRANSFORMS.values()):
    """Upload an image to cloudinary"""
    response = upload(path, tags=tag)
    urls = {"original": response["url"]}

    format_ = response["format"]
    public_id = response["public_id"]
    for transform in transforms:
        urls[transform] = image_url(public_id, format_, transform)

    return urls
