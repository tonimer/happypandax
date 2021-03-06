from collections import namedtuple
from sqlalchemy.sql.expression import func
from sqlalchemy_utils.functions import make_order_by_deterministic

from happypanda.common import utils, hlogger, exceptions, constants, config
from happypanda.core.command import Command, CommandEvent, AsyncCommand, CommandEntry
from happypanda.core.commands import io_cmd
from happypanda.core import db, async
from happypanda.interface import enums
from happypanda.interface.enums import ItemSort

log = hlogger.Logger(constants.log_ns_command + __name__)


class GetModelImage(AsyncCommand):
    """
    Fetch a database model item's image

    By default, the following models are supported

    - Gallery
    - Page
    - Grouping
    - Collection
    - GalleryFilter

    Returns a Profile database item
    """

    models = CommandEntry("models", tuple)
    generate = CommandEntry("generate", str, str, int, utils.ImageSize)
    invalidate = CommandEntry("invalidate", bool, str, int, utils.ImageSize)

    cover_event = CommandEvent('cover', object)

    def __init__(self, service=None):
        super().__init__(service, priority=constants.Priority.Low)
        self.model = None
        self.cover = None
        self._supported_models = set()

    @models.default()
    def _models():
        return (
            db.Grouping,
            db.Collection,
            db.Gallery,
            db.Page,
            db.GalleryFilter
        )

    @generate.default(capture=True)
    def _generate_gallery_and_page(model, item_id, size, capture=[db.model_name(x) for x in (db.Page, db.Gallery)]):
        im_path = ""
        model = GetModelClass().run(model)

        if model == db.Gallery:
            page = GetSession().run().query(
                db.Page.path).filter(
                db.and_op(
                    db.Page.gallery_id == item_id,
                    db.Page.number == 1)).one_or_none()
        else:
            page = GetSession().run().query(db.Page.path).filter(db.Page.id == item_id).one_or_none()

        if page:
            im_path = page[0]

        if im_path:
            im_props = io_cmd.ImageProperties(size, 0, constants.dir_thumbs)
            im_path = io_cmd.ImageItem(im_path, im_props).main()
        return im_path

    @invalidate.default(capture=True)
    def _invalidate_gallery_and_page(model, item_id, size, capture=[db.model_name(x) for x in (db.Page, db.Gallery)]):
        return False

    @generate.default(capture=True)
    def _generate_collection(model, item_id, size, capture=db.model_name(db.Collection)):
        im_path = ""
        model = GetModelClass().run(model)

        page = GetSession().run().query(
            db.Page.path).join(db.Collection.galleries).join(db.Gallery.pages).filter(
            db.and_op(
                db.Collection.id == item_id,
                db.Page.number == 1)).first()

        # gallery sorted by insertion:
        # page = GetSession().run().query(
        #    db.Page.path, db.gallery_collections.c.timestamp.label("timestamp")).join(db.Collection.galleries).join(db.Gallery.pages).filter(
        #    db.and_op(
        #        db.Collection.id == item_id,
        #        db.Page.number == 1)).sort_by("timestamp").first()
        if page:
            im_path = page[0]

        if im_path:
            im_props = io_cmd.ImageProperties(size, 0, constants.dir_thumbs)
            im_path = io_cmd.ImageItem(im_path, im_props).main()
        return im_path

    @invalidate.default(capture=True)
    def _invalidate_collection(model, item_id, size, capture=db.model_name(db.Collection)):
        return False

    def main(self, model: db.Base, item_id: int,
             image_size: enums.ImageSize) -> db.Profile:
        self.model = model

        if image_size == enums.ImageSize.Original:
            image_size = utils.ImageSize(0, 0)
        else:
            image_size = utils.ImageSize(*constants.image_sizes[image_size.name.lower()])

        with self.models.call() as plg:
            for p in plg.all(default=True):
                self._supported_models.update(p)

        if self.model not in self._supported_models:
            raise exceptions.CommandError(
                utils.this_command(self),
                "Model '{}' is not supported".format(model))

        img_hash = io_cmd.ImageItem.gen_hash(
            model, image_size, item_id)

        generate = True
        sess = constants.db_session()

        profile_size = str(tuple(image_size))

        self.cover = sess.query(
            db.Profile).filter(
            db.and_op(
                db.Profile.data == img_hash,
                db.Profile.size == profile_size)).first()

        old_img_hash = None
        if self.cover:
            if io_cmd.CoreFS(self.cover.path).exists:
                generate = False
            else:
                old_img_hash = self.cover.data

        self.next_progress()
        if not generate:
            model_name = db.model_name(model)
            with self.invalidate.call_capture(model_name, model_name, item_id, image_size) as plg:
                if plg.first():
                    generate = True

        self.next_progress()
        if generate:
            self.cover = self.run_native(self._generate_and_add, img_hash, old_img_hash, generate,
                                         model, item_id, image_size, profile_size).get()
        self.cover_event.emit(self.cover)
        return self.cover

    @async.defer
    def _update_db(self, stale_cover, item_id, model, old_hash):
        log.d("Updating profile for database item", model)
        s = constants.db_session()
        cover = s.query(db.Profile).filter(
            db.and_op(db.Profile.data == old_hash, db.Profile.size == stale_cover.size)).all()

        if len(cover) > 1:
            cover, *cover_ex = cover
            for x in cover_ex:
                s.delete(x)
        elif cover:
            cover = cover[0]

        new = False

        if cover:
            # sometimes an identical img has already been generated and exists so we shouldnt do anything
            fs = io_cmd.CoreFS(cover.path)
            if (cover.path != stale_cover.path) and fs.exists:
                fs.delete()
        else:
            cover = db.Profile()
            new = True

        cover.data = stale_cover.data
        cover.path = stale_cover.path
        cover.size = stale_cover.size

        if new or not s.query(db.Profile).join(db.relationship_column(model, db.Profile)).filter(
                db.and_op(db.Profile.id == cover.id, model.id == item_id)).scalar():
            log.d("Adding new profile to database item", model, "()".format(item_id))
            i = s.query(model).get(item_id)
            i.profiles.append(cover)

        s.commit()
        self.next_progress()

    def _generate_and_add(self, img_hash, old_img_hash, generate, model, item_id, image_size, profile_size):

        model_name = db.model_name(model)

        cover = db.Profile()
        if generate:
            log.d("Generating new profile", image_size, "for database item", model)
            with self.generate.call_capture(model_name, model_name, item_id, image_size) as plg:
                p = plg.first()
                if not p:
                    p = ""
                cover.path = p

            cover.data = img_hash
            cover.size = profile_size
        self.next_progress()
        if cover.path and generate:
            log.d("Updating database")
            self._update_db(cover, item_id, model, old_img_hash)
        elif not cover.path:
            cover = None
        return cover


class GetModelClass(Command):
    """
    Returns a database model by name
    """

    def __init__(self):
        super().__init__()

    def main(self, model_name: str) -> db.Base:

        if not hasattr(db, model_name):
            raise exceptions.CoreError(
                utils.this_command(self),
                "No database model named '{}'".format(model_name))

        return getattr(db, model_name)


class GetSession(Command):
    """
    Returns a database session
    """

    def __init__(self):
        super().__init__()

    def main(self) -> db.scoped_session:
        return constants.db_session()


class GetDatabaseSort(Command):
    """
    Returns a name or, a namedtuple(expr, joins) of a data sort expression and additional
    tables to join, for a given sort index
    """

    names = CommandEntry("names", dict, str)

    orderby = CommandEntry("orderby", dict, str)

    groupby = CommandEntry("groupby", dict, str)

    joins = CommandEntry("joins", dict, str)

    SortTuple = namedtuple("SortTuple", ["orderby", "joins", "groupby"])

    def __init__(self):
        super().__init__()
        self.model = None

    ##############################
    # Gallery

    @names.default(capture=True)
    def _gallery_names(model_name, capture=db.model_name(db.Gallery)):
        return {
            ItemSort.GalleryRandom.value: "Random",
            ItemSort.GalleryTitle.value: "Title",
            ItemSort.GalleryArtist.value: "Artist",
            ItemSort.GalleryDate.value: "Date Added",
            ItemSort.GalleryPublished.value: "Date Published",
            ItemSort.GalleryRead.value: "Last Read",
            ItemSort.GalleryUpdated.value: "Last Updated",
            ItemSort.GalleryRating.value: "Rating",
            ItemSort.GalleryReadCount.value: "Read Count",
            ItemSort.GalleryPageCount.value: "Page Count",
        }

    @orderby.default(capture=True)
    def _gallery_orderby(model_name, capture=db.model_name(db.Gallery)):
        return {
            ItemSort.GalleryRandom.value: (func.random(),),
            ItemSort.GalleryTitle.value: (db.Title.name,),
            ItemSort.GalleryArtist.value: (db.AliasName.name,),
            ItemSort.GalleryDate.value: (db.Gallery.timestamp,),
            ItemSort.GalleryPublished.value: (db.Gallery.pub_date,),
            ItemSort.GalleryRead.value: (db.Gallery.last_read,),
            ItemSort.GalleryUpdated.value: (db.Gallery.last_updated,),
            ItemSort.GalleryRating.value: (db.Gallery.rating,),
            ItemSort.GalleryReadCount.value: (db.Gallery.times_read,),
            ItemSort.GalleryPageCount.value: (db.func.count(db.Page.id),),
        }

    @groupby.default(capture=True)
    def _gallery_groupby(model_name, capture=db.model_name(db.Gallery)):
        return {
            ItemSort.GalleryPageCount.value: (db.Gallery.id,),
        }

    @joins.default(capture=True)
    def _gallery_joins(model_name, capture=db.model_name(db.Gallery)):
        return {
            ItemSort.GalleryTitle.value: (db.Gallery.titles,),
            ItemSort.GalleryArtist.value: (db.Gallery.artists, db.Artist.names,),
            ItemSort.GalleryPageCount.value: (db.Gallery.pages,),
        }

    ##############################
    # Collection

    @names.default(capture=True)
    def _collection_names(model_name, capture=db.model_name(db.Collection)):
        return {
            ItemSort.CollectionRandom.value: "Random",
            ItemSort.CollectionName.value: "Name",
            ItemSort.CollectionDate.value: "Date Added",
            ItemSort.CollectionPublished.value: "Date Published",
            ItemSort.CollectionGalleryCount.value: "Gallery Count",
        }

    @orderby.default(capture=True)
    def _collection_orderby(model_name, capture=db.model_name(db.Collection)):
        return {
            ItemSort.CollectionRandom.value: (func.random(),),
            ItemSort.CollectionName.value: (db.Collection.name,),
            ItemSort.CollectionDate.value: (db.Collection.timestamp,),
            ItemSort.CollectionPublished.value: (db.Collection.pub_date,),
            ItemSort.CollectionGalleryCount.value: (db.func.count(db.Gallery.id),),
        }

    @groupby.default(capture=True)
    def _collection_groupby(model_name, capture=db.model_name(db.Collection)):
        return {
            ItemSort.CollectionGalleryCount.value: (db.Collection.id,),
        }

    @joins.default(capture=True)
    def _collection_joins(model_name, capture=db.model_name(db.Collection)):
        return {
            ItemSort.CollectionGalleryCount.value: (db.Collection.galleries,),
        }

    ##############################
    # AliasName

    @names.default(capture=True)
    def _aliasname_names(model_name, capture=tuple(db.model_name(x) for x in (db.Artist, db.Parody))):
        return {
            ItemSort.ArtistName.value: "Name",
            ItemSort.ParodyName.value: "Name",
        }

    @orderby.default(capture=True)
    def _aliasname_orderby(model_name, capture=tuple(db.model_name(x) for x in (db.Artist, db.Parody))):
        return {
            ItemSort.ArtistName.value: (db.AliasName.name,),
            ItemSort.ParodyName.value: (db.AliasName.name,),
        }

    @joins.default(capture=True)
    def _aliasname_joins(model_name, capture=tuple(db.model_name(x) for x in (db.Artist, db.Parody))):
        return {
            ItemSort.ArtistName.value: (db.Artist.names,),
            ItemSort.ParodyName.value: (db.Parody.names,),
        }

    ##############################
    # Circle

    @names.default(capture=True)
    def _circle_names(model_name, capture=db.model_name(db.Circle)):
        return {
            ItemSort.CircleName.value: "Name",
        }

    @orderby.default(capture=True)
    def _circle_orderby(model_name, capture=db.model_name(db.Circle)):
        return {
            ItemSort.CircleName.value: (db.Circle.name,),
        }

    @joins.default(capture=True)
    def _circle_joins(model_name, capture=db.model_name(db.Circle)):
        return {
        }

    ##############################
    # NamespaceTags

    @names.default(capture=True)
    def _namespacetags_names(model_name, capture=db.model_name(db.NamespaceTags)):
        return {
            ItemSort.NamespaceTagNamespace.value: "Namespace",
            ItemSort.NamespaceTagTag.value: "Tag",
        }

    @orderby.default(capture=True)
    def _namespacetags_orderby(model_name, capture=db.model_name(db.NamespaceTags)):
        return {
            ItemSort.NamespaceTagNamespace.value: (db.Namespace.name, db.Tag.name),
            ItemSort.NamespaceTagTag.value: (db.Tag.name, db.Namespace.name),
        }

    @joins.default(capture=True)
    def _namespacetags_joins(model_name, capture=db.model_name(db.NamespaceTags)):
        return {
            ItemSort.NamespaceTagNamespace.value: (db.NamespaceTags.namespace, db.NamespaceTags.tag),
            ItemSort.NamespaceTagTag.value: (db.NamespaceTags.tag, db.NamespaceTags.namespace),
        }

    def main(self, model: db.Base, sort_index: int=None, name: bool=False) -> object:
        self.model = model
        model_name = db.model_name(self.model)
        items = {}
        if name:
            with self.names.call_capture(model_name, model_name) as plg:
                for x in plg.all(default=True):
                    items.update(x)
        else:
            orders = {}
            with self.orderby.call_capture(model_name, model_name) as plg:
                for x in plg.all(default=True):
                    orders.update(x)

            groups = {}
            with self.groupby.call_capture(model_name, model_name) as plg:
                for x in plg.all(default=True):
                    groups.update(x)

            joins = {}
            with self.joins.call_capture(model_name, model_name) as plg:
                for x in plg.all(default=True):
                    joins.update(x)

            for k, v in orders.items():
                a = v
                b = tuple()
                c = None
                if k in joins:
                    t = joins[k]
                    if isinstance(t, tuple):
                        b = t
                if k in groups:
                    c = groups[k]
                items[k] = self.SortTuple(a, b, c)

        return items.get(sort_index) if sort_index else items


class GetModelItems(Command):
    """
    Fetch model items from the database

    Returns a tuple of model items
    """

    fetched = CommandEvent("fetched", str, tuple)

    count = CommandEvent("count", str, int)

    def __init__(self):
        super().__init__()

        self.fetched_items = tuple()

    def _query(self, q, limit, offset):
        if offset:
            q = q.offset(offset)

        return q.limit(limit).all()

    def _get_sql(self, expr):
        if isinstance(expr, str):
            return db.sa_text(expr)
        else:
            return expr

    def _get_count(self, q):
        return q.count()

    def main(self, model: db.Base, ids: set = None, limit: int = 999,
             filter: str = None, order_by: str = None, group_by: str=None,
             offset: int = 0, columns: tuple = tuple(),
             join: str = None, count: bool = False) -> tuple:
        if ids is None:
            log.d("Fetching items", "offset:", offset, "limit:", limit)
        else:
            log.d("Fetching items from a set with", len(ids), "ids", "offset:", offset, "limit:", limit)

        if not offset:
            offset = 0
        if not limit:
            limit = 0

        if (ids is not None and not ids) or\
           (ids and len(ids) == 1 and all(x == 0 for x in ids)):
            return 0 if count else tuple()

        criteria = False

        s = constants.db_session()
        if count:
            q = s.query(model.id)
        elif columns:
            q = s.query(*columns)
        else:
            q = s.query(model)

        if join is not None:
            criteria = True
            if not isinstance(join, (list, tuple)):
                join = [join]
            for j in join:
                q = q.join(self._get_sql(j))

        if group_by is not None:
            criteria = True
            if not isinstance(group_by, (list, tuple)):
                group_by = [group_by]
            q = q.group_by(*(self._get_sql(g) for g in group_by))

        if order_by is not None:
            criteria = True
            if not isinstance(order_by, (list, tuple)):
                order_by = [order_by]
            q = make_order_by_deterministic(q.order_by(*(self._get_sql(o) for o in order_by)))

        if filter is not None:
            criteria = True
            q = q.filter(self._get_sql(filter))

        if ids:
            id_amount = len(ids)
            _max_variables = 900
            if id_amount > _max_variables and config.dialect.value == constants.Dialect.SQLITE:
                if count:
                    fetched_list = [x for x in q.all() if x[0] in ids]
                else:
                    fetched_list = [x for x in q.all() if x.id in ids]
                    fetched_list = fetched_list[offset:][:limit]

                self.fetched_items = tuple(fetched_list) if not count else len(fetched_list)
            elif id_amount == 1 and (not columns and not criteria):
                self.fetched_items = (q.get(ids.pop()),) if not count else self._get_count(q)
            else:
                q = q.filter(model.id.in_(ids))
                self.fetched_items = tuple(self._query(q, limit, offset)) if not count else self._get_count(q)
        else:
            self.fetched_items = tuple(self._query(q, limit, offset)) if not count else self._get_count(q)

        if count:
            self.count.emit(db.model_name(model), self.fetched_items)
            log.d("Returning items count ", self.fetched_items)
        else:
            self.fetched.emit(db.model_name(model), self.fetched_items)
            self.count.emit(db.model_name(model), len(self.fetched_items))
            log.d("Returning", len(self.fetched_items), "fetched items")
        return self.fetched_items


class MostCommonTags(Command):
    """
    Get the most common tags for item
    """

    def main(self, model: db.Base, item_id: int, limit: int=20) -> tuple:
        assert issubclass(model, (db.Artist, db.Grouping, db.Collection))

        s = constants.db_session()
        r = s.query(db.NamespaceTags).join(
            db.Taggable.tags).filter(
            db.Taggable.id.in_(
                s.query(
                    db.Gallery.taggable_id).join(
                    model.galleries).filter(
                    model.id == item_id))
        ).group_by(db.NamespaceTags).order_by(
            db.desc_expr(db.func.count(db.NamespaceTags.id))).limit(limit).all()
        return tuple(r)
