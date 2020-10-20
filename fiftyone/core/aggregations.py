"""
Aggregations.

| Copyright 2017-2020, Voxel51, Inc.
| `voxel51.com <https://voxel51.com/>`_
|
"""
from bson import ObjectId

import eta.core.serial as etas

import fiftyone.core.fields as fof
import fiftyone.core.labels as fol
import fiftyone.core.utils as fou

_LABELS = (fol.Classifications, fol.Detections, fol.Keypoints, fol.Polylines)
_NUMBER_FIELDS = (fof.IntField, fof.FloatField)
_VALUE_FIELDS = (fof.BooleanField, fof.IntField, fof.StringField)


def _attach_and_unwind_frames(dataset):
    return [
        {
            "$lookup": {
                "from": dataset._frame_collection_name,
                "localField": "_id",
                "foreignField": "_sample_id",
                "as": "frames",
            }
        },
        {"$unwind": "frames"},
    ]


class Aggregation(object):
    """Abstract base class for all aggregations.

    :class:`Aggregation` instances represent an aggregation or reduction
    of a :class:`fiftyone.core.collections.SampleCollection` instance.
    """

    def __init__(self, field_name):
        self._field_name = field_name

    def _get_default_result(self):
        raise NotImplementedError(
            "Subclass must implement _get_default_result()"
        )

    def _get_output_field(self, schema, frame_schema):
        raise NotImplementedError(
            "Subclass must implement _get_output_field()"
        )

    def _get_result(self, d):
        raise NotImplementedError("Subclass must implement _get_result()")

    def _to_mongo(self, dataset, schema, frame_schema):
        raise NotImplementedError("Subclass must implement _to_mongo()")

    @staticmethod
    def _get_field_path_pipeline(field_name, schema, frame_schema, dataset):
        try:
            field = schema[field_name]
            path = "$%s" % field_name
            return field, path, []
        except:
            try:
                field = frame_schema["frames"][field_name]
                path = "$frames.%s" % field_name
                return field, path, _attach_and_unwind_frames(dataset)
            except:
                pass

        raise AggregationError(
            "field `%s` does not exist on this Dataset" % field_name
        )


class AggregationResult(etas.Serializable):
    """Abstract base class for all aggregation results.
    
    :class:`AggregationResult` instances represent the result of the execution
    of an :class:`Aggregation` on a :class:`fiftyone.core.collection.SampleCollection`.
    """

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        d = {}
        for f in self.attributes():
            value = getattr(self, f)
            if isinstance(value, ObjectId):
                d[f] = str(value)
            else:
                d[f] = value

        class_name = self.__class__.__name__
        out = fou.pformat(d)
        return "<%s: %s>" % (class_name, fou.pformat(d))


class AggregationError(RuntimeError):

    pass


class Bounds(Aggregation):
    """Computes the inclusive bounds of a numeric field or a list field of
    numeric field in a view.

    Note that to compute bounds on a list field of numeric fields, the
    numeric subfield must be explicitly defined.

    Examples::
        import fiftyone as fo
        from fiftyone.core.aggregations import Bounds

        dataset = fo.load_dataset(...)

        #
        # Compute the bounds of a numeric field
        #

        bounds = fo.Bounds("uniqueness")
        bounds_result = dataset.aggregate(bounds)
        bounds_result.bounds # (min, max) inclusive bounds tuple

        #
        # Compute the a bounds of a list field of a numeric field
        #
        # assume the list field was instantiated on the dataset with a call to
        # dataset.add_sample_field()
        #

        dataset.add_sample_field(fo.ListField, subfield=fo.FloatField())
        list_bounds = fo.Bounds("uniqueness_trials")
        list_bounds_result = dataset.aggregate(list_bounds)
        list_bounds_result.bounds # (min, max) inclusive bounds tuple
    
    Args:
        field_name: the name of the field to compute bounds for
    """

    def __init__(self, field_name):
        super().__init__(field_name)

    def _get_default_result(self):
        return BoundsResult(self._field_name, (None, None))

    def _get_output_field(self, view):
        return "%s-bounds" % self._field_name

    def _get_result(self, d):
        mn = d["min"]
        mx = d["max"]
        return ConfidenceBoundsResult(self._field_name, (mn, mx))

    def _to_mongo(self, dataset, schema, frame_schema):
        field, path, pipeline = self._get_field_path_pipeline(
            self._field_name, schema, frame_schema, dataset
        )
        if isinstance(field, fof.ListField) and isinstance(
            field.field, _NUMBER_FIELDS
        ):
            unwind = True
        elif isinstance(field, _NUMBER_FIELDS):
            unwind = False
        else:
            raise AggregationError(
                "unsupported field '%s' of type '%s' for this Dataset"
                % (self._field_name, type(field))
            )

        path = "$%s" % self._field_name
        pipeline += [
            {"$project": {self._field_name: path}},
            {
                "$group": {
                    "_id": None,
                    "min": {"$min": path},
                    "max": {"$max": path},
                }
            },
        ]
        if unwind:
            pipeline = (
                pipeline[: len(pipeline) - 1]
                + [{"$unwind": path}]
                + pipeline[len(pipeline) - 1 :]
            )

        return pipeline


class BoundsResult(AggregationResult):
    """The result of the execution :class:`Bounds` by a dataset.

    Attributes:
        name: the name of the field
        bounds: the inclusive (min, max) bounds tuple
    """

    def __init__(self, field_name, bounds):
        self.name = field_name
        self.bounds = bounds


class ConfidenceBounds(Aggregation):
    """Computes the inclusive bounds of the confidences of
    :class:`fiftyone.core.labels.Label`

    Examples::
        import fiftyone as fo
        from fiftyone.core.aggregations import Bounds

        dataset = fo.load_dataset(...)

        #
        # Compute the confidence bounds of a fo.Classification label field
        #

        bounds = fo.ConfidenceBounds("predictions")
        bounds_result = dataset.aggregate(bounds)
        bounds_result.bounds # (min, max) inclusive confidence bounds tuple

        #
        # Compute the a confidence bounds a fo.Detections label field
        #

        detections_bounds = fo.Bounds("detections")
        detections_bounds_result = dataset.aggregate(detections_bounds)
        detections_bounds_result.bounds # (min, max) inclusive bounds tuple
    
    Args:
        field_name: the name of the label field to compute confidence bounds
            for
    """

    def __init__(self, field_name):
        super().__init__(field_name)

    def _get_default_result(self):
        return ConfidenceBoundsResult(self._field_name, (None, None))

    def _get_output_field(self, view):
        return "%s-confidence-bounds" % self._field_name

    def _get_result(self, d):
        mn = d["min"]
        mx = d["max"]
        return ConfidenceBoundsResult(self._field_name, (mn, mx))

    def _to_mongo(self, dataset, schema, frame_schema):
        field, path, pipeline = self._get_field_path_pipeline(
            self._field_name, schema, frame_schema, dataset
        )
        if not isinstance(field, fof.EmbeddedDocumentField) or not issubclass(
            field.document_type, fol.Label
        ):
            raise AggregationError("field '%s' is not a label")

        if field.document_type in _LABELS:
            path = "%s.%s" % (path, field.document_type.__name__.lower())
            pipeline.append(
                {"$unwind": {"path": path, "preserveNullAndEmptyArrays": True}}
            )

        path = "%s.confidence" % path
        pipeline += [
            {
                "$group": {
                    "_id": None,
                    "min": {"$min": path},
                    "max": {"$max": path},
                }
            },
        ]

        return pipeline


class ConfidenceBoundsResult(AggregationResult):
    """The result of the execution :class:`ConfidenceBounds` by a dataset.

    Attributes:
        name: the name of the field
        bounds: the inclusive (min, max) confidence bounds tuple
    """

    def __init__(self, field_name, bounds):
        self.name = field_name
        self.bounds = bounds


class Count(Aggregation):
    """Counts the items with respect to a field, or the number of samples if
    no field_name is provided.

    Examples:
        @todo
    """

    def __init__(self, field_name=None):
        super().__init__(field_name)

    def _get_default_result(self):
        return CountResult(self._field_name, 0)

    def _get_output_field(self, view):
        if self._field_name is None:
            return "count"

        return "%s-count" % self._field_name

    def _get_result(self, d):
        return CountResult(self._field_name, d["count"])

    def _to_mongo(self, dataset, schema, frame_schema):
        if self._field_name is None:
            return [{"$count": "count"}]

        field, path, pipeline = self._get_field_path_pipeline(
            self._field_name, schema, frame_schema, dataset
        )

        if (
            isinstance(field, fof.EmbeddedDocumentField)
            and field.document_type in _LABELS
        ):
            path = "%s.%s" % (path, field.document_type.__name__.lower())
            pipeline.append({"$unwind": path})
        elif isinstance(field, fof.ListField):
            pipeline.append({"$unwind": path})

        return pipeline + [{"$count": "count"}]


class CountResult(AggregationResult):
    def __init__(self, field_name, count):
        self._field_name = field_name
        self.name = field_name
        if field_name is None:
            self.name = "TotalCount"
        self.count = count


class Distinct(Aggregation):
    def __init__(self, field_name):
        super().__init__(field_name)

    def _get_default_result(self):
        return DistinctResult(self._field_name, [])

    def _get_output_field(self, view):
        return "%s-distinct" % self._field_name

    def _get_result(self, d):
        return DistinctResult(self._field_name, sorted(d[self._field_name]))

    def _to_mongo(self, dataset, schema, frame_schema):
        field, path, pipeline = self._get_field_path_pipeline(
            self._field_name, schema, frame_schema, dataset
        )
        if isinstance(field, fof.ListField) and isinstance(
            field.field, _VALUE_FIELDS
        ):
            unwind = True
        elif isinstance(field, _VALUE_FIELDS):
            unwind = False
        else:
            raise AggregationError(
                "unsupported field '%s' of type '%s' for this Dataset"
                % (self._field_name, type(field))
            )

        pipeline += [
            {"$project": {self._field_name: path}},
            {
                "$group": {
                    "_id": "None",
                    self._field_name: {"$addToSet": path},
                }
            },
        ]

        if unwind:
            pipeline = (
                pipeline[: len(pipeline) - 1]
                + [{"$unwind": path}]
                + pipeline[len(pipeline) - 1 :]
            )

        return pipeline


class DistinctResult(AggregationResult):
    def __init__(self, field_name, values):
        self.name = field_name
        self.values = values


class DistinctLabels(Aggregation):
    def __init__(self, field_name):
        super().__init__(field_name)

    def _get_default_result(self):
        return DistinctLabelsResult(self._field_name, [])

    def _get_output_field(self, view):
        return "%s-distinct-labels" % self._field_name

    def _get_result(self, d):
        return DistinctLabelsResult(self._field_name, sorted(d["labels"]))

    def _to_mongo(self, dataset, schema, frame_schema):
        field, path, pipeline = self._get_field_path_pipeline(
            self._field_name, schema, frame_schema, dataset
        )
        if not isinstance(field, fof.EmbeddedDocumentField) or not issubclass(
            field.document_type, fol.Label
        ):
            raise AggregationError("field '%s' is not a label")

        if field.document_type in _LABELS:
            path = "%s.%s" % (path, field.document_type.__name__.lower())
            pipeline.append(
                {"$unwind": {"path": path, "preserveNullAndEmptyArrays": True}}
            )

        path = "%s.label" % path
        pipeline.append(
            {"$group": {"_id": None, "labels": {"$addToSet": path}}}
        )

        return pipeline


class DistinctLabelsResult(AggregationResult):
    def __init__(self, field_name, labels):
        self.name = field_name
        self.labels = labels
