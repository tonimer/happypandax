"""
Enums
----------------------------------------

Enums can be used by their member names and values interchangeably.
Enum member names are case insensitive::

    ItemType.Gallery == 1 # true
    ItemType.Gallery == ItemType.gaLLeRy # true

It is recommended that enum members are used by their *values* and not names.
Enum member names may change sometime in the future. It is not likely to happen but no promises.

"""

import enum

from happypanda.common import utils, exceptions
from happypanda.core import message, db


class _APIEnum(enum.Enum):
    "A conv. enum class"

    @classmethod
    def get(cls, key):

        # for some ungodly unknown reason this check wouldnt work when calling from the client
        # so i ended up comparing strings instead
        if repr(type(key)) == repr(cls):
            return key
        if key is not None:
            try:
                return cls[key]
            except KeyError:
                pass

            try:
                return cls(key)
            except ValueError:
                pass

            if isinstance(key, str):
                low_key = key.lower()
                for name, member in cls.__members__.items():
                    if name.lower() == low_key:
                        return member

        raise exceptions.EnumError(
            utils.this_function(),
            "{}: enum member doesn't exist '{}'".format(
                cls.__name__,
                repr(key)))


class ViewType(_APIEnum):
    #: Library
    Library = 1
    #: Favourite
    Favorite = 2
    #: Inbox
    Inbox = 3
    #: Trash
    Trash = 4
    #: Read Later
    ReadLater = 5


class ItemType(_APIEnum):
    #: Gallery
    Gallery = 1
    #: Collection
    Collection = 2
    #: GalleryFilter
    GalleryFilter = 3
    #: Page
    Page = 4
    #: Gallery Namespace
    Grouping = 5
    #: Gallery Title
    Title = 6
    #: Gallery Artist
    Artist = 7
    #: Category
    Category = 8
    #: Language
    Language = 9
    #: Status
    Status = 10
    #: Circle
    Circle = 11
    #: URL
    Url = 12
    #: Gallery Parody
    Parody = 13

    def _msg_and_model(item_type, allowed=tuple(), error=True):
        """
        Get the equivalent Message and Database object classes for ItemType member

        Args:
            allowed: a tuple of ItemType members which are allowed, empty tuple for all members
            error: raise error if equivalent is not found, else return generic message object class
        """
        if allowed and repr(item_type) not in (repr(x) for x in allowed):
            raise exceptions.APIError(
                utils.this_function(),
                "ItemType must be on of {} not '{}'".format(
                    allowed,
                    repr(item_type)))

        db_model = None
        try:
            db_model = getattr(db, item_type.name)
        except AttributeError:
            if error:
                raise exceptions.CoreError(utils.this_function(),
                                           "Equivalent database object class for {} was not found".format(item_type))

        obj = None
        try:
            obj = getattr(message, item_type.name)
        except AttributeError:
            try:
                if db_model and issubclass(db_model, db.NameMixin):
                    obj = getattr(message, db.NameMixin.__name__)
            except AttributeError:
                pass
            if not obj:
                if error:
                    raise exceptions.CoreError(utils.this_function(),
                                               "Equivalent Message object class for {} was not found".format(item_type))
                obj = message.DatabaseMessage

        return obj, db_model


class ImageSize(_APIEnum):
    #: Original image size
    Original = 1
    #: Big image size
    Big = 2
    #: Medium image size
    Medium = 3
    #: Small image size
    Small = 4


class ServerCommand(_APIEnum):
    #: Shut down the server
    ServerQuit = 1

    #: Restart the server
    ServerRestart = 2

    #: Request authentication
    RequestAuth = 3


class ItemSort(_APIEnum):

    #: Gallery Random
    GalleryRandom = 1
    #: Gallery Title
    GalleryTitle = 2
    #: Gallery Artist Name
    GalleryArtist = 3
    #: Gallery Date Added
    GalleryDate = 4
    #: Gallery Date Published
    GalleryPublished = 5
    #: Gallery Last Read
    GalleryRead = 6
    #: Gallery Last Updated
    GalleryUpdated = 7
    #: Gallery Rating
    GalleryRating = 8
    #: Gallery Read Count
    GalleryReadCount = 9
    #: Gallery Page Count
    GalleryPageCount = 10

    #: Artist Name
    ArtistName = 20

    #: Namespace
    NamespaceTagNamespace = 30
    #: Tag
    NamespaceTagTag = 31

    #: Circle Name
    CircleName = 40

    #: Parody Name
    ParodyName = 45

    #: Collection Random
    CollectionRandom = 50
    #: Collection Name
    CollectionName = 51
    #: Collection Date Added
    CollectionDate = 52
    #: Collection Date Published
    CollectionPublished = 53
    #: Collection Gallery Count
    CollectionGalleryCount = 54


class ProgressType(_APIEnum):

    #: Unknown
    Unknown = 1
    #: Network request
    Request = 2
    #: A check for new update
    CheckUpdate = 3
    #: Updating application
    UpdateApplication = 4
