import abc
import builtins
import importlib

from hotsos.core.log import log
from hotsos.core.ystruct import (
    YStructOverrideBase,
    YStructMappedOverrideBase,
    YStructSection,
)


YPropertiesCatalog = []


class YDefsSection(YStructSection):

    def __init__(self, name, content, context=None):
        """
        @param name: name of defs group
        @param content: defs tree of type dict
        @param context: optional context object. This gets passed to all
                        resolved properties and can be used to share
                        information amongst them. If one is no provided
                        a new empty one is created.
        """
        super().__init__(name, content, override_handlers=YPropertiesCatalog,
                         context=context or YDefsContext())


def add_to_property_catalog(c):
    """
    Add property implementation to the global catalog.
    """
    YPropertiesCatalog.append(c)
    return c


def cached_yproperty_attr(f):
    """
    This can be used to cache a yproperty attribute property e.g. to avoid
    expensive re-execution of that property with successive calls.
    """
    @property
    def _inner(inst):
        # we prefix the keyname so as to avoid collisions with non attribute
        # items added to the cache.
        key = "__yproperty_attr__{}".format(f.__name__)
        ret = getattr(inst.cache, key)
        if ret is not None:
            return ret

        ret = f(inst)
        inst.cache.set(key, ret)
        return ret

    return _inner


class YDefsContext(object):
    """
    Provides a way to get/set arbitrary information used as context to a yaml
    defs run. This object is typically passed to a YDefsSection and accessible
    from all override properties as attribute "context".
    """
    def __init__(self, initial_state=None):
        """
        @param initial_state: optional dict to use as initial state.
        """
        self._ydefs_context = initial_state or {}

    def __setattr__(self, key, value):
        if key != '_ydefs_context':
            log.debug("%s setting %s=%s", self.__class__.__name__, key, value)
            self._ydefs_context[key] = value
            return

        super().__setattr__(key, value)

    def __getattr__(self, key):
        return self._ydefs_context.get(key)


class PropertyCacheRefResolver(object):
    """
    This class is used to resolve string references to property cache entries.
    """
    def __init__(self, refstr, vars=None, checks=None):
        log.debug("%s: resolving '%s'", self.__class__.__name__, refstr)
        self.refstr = refstr
        if not self.is_valid_cache_ref(refstr):
            msg = ("{} is not a valid property cache reference or variable".
                   format(refstr))
            raise Exception(msg)

        self.vars = vars
        self.checks = checks
        if self.reftype == 'checks' and checks is None:
            msg = ("{} is a checks cache reference but checks dict not "
                   "provided".format(refstr))
            raise Exception(msg)

    @property
    def reftype(self):
        """
        These depict the type of property or propertycollection that can be
        referenced.

        Supported formats:
            $varname[:func]
            @checks.<check_name>.<property_name>.<property_cache_key>[:func]
        """
        if self.refstr.startswith('$'):
            return "variable"
        elif self.refstr.startswith('@checks.'):
            # This is an implementation of YPropertyChecks
            return "checks"
        else:
            raise Exception("unknown ref type")

    @property
    def _ref_body(self):
        """
        Strip the prefix from the reference string.
        """
        if self.reftype == 'variable':
            prefix = "$"
        elif self.reftype == 'checks':
            prefix = "@checks.{}.".format(self.check_name)

        return self.refstr.partition(prefix)[2]

    @classmethod
    def is_valid_cache_ref(cls, refstr):
        """
        Returns True if refstr is a valid property cache reference.

        The criteria for a valid reference is that it must be a string whose
        first character is @.
        """
        if type(refstr) != str:
            return False

        if not (refstr.startswith('@') or refstr.startswith('$')):
            return False

        return True

    @property
    def check_name(self):
        if self.reftype != 'checks':
            raise Exception("ref does not have type 'checks'")

        return self.refstr.partition('@checks.')[2].partition('.')[0]

    @property
    def property_name(self):
        if self.reftype == 'checks':
            return self._ref_body.partition('.')[0]

    @property
    def property_cache_key(self):
        """ Key for PropertyCache. """
        if self.reftype == 'checks':
            _key = self._ref_body.partition('.')[2]
        else:
            raise Exception("not a check reftype")

        # strip func if exists
        return _key.partition(':')[0]

    @property
    def property_cache_value_renderer_function(self):
        """
        This is an optional function name that can be provided as the last
        item in the reference string seperated by a colon.
        """
        if self.reftype == 'checks':
            _key = self._ref_body.partition('.')[2]
        else:
            _key = self._ref_body

        return _key.partition(':')[2]

    def apply_renderer_function(self, value):
        """
        The last section of a ref string can be a colon followed by a function
        name which itself can be one of two things; any method supported by
        builtins or "comma_join".
        """
        func = self.property_cache_value_renderer_function
        if func:
            if func == "comma_join":
                # needless to say this will only work with lists, dicts etc.
                return ', '.join(value)

            return getattr(builtins, func)(value)

        return value

    def resolve(self):
        if self.reftype == 'checks':
            check_cache = self.checks[self.check_name].cache
            property_cache = getattr(check_cache, self.property_name)
            val = getattr(property_cache, self.property_cache_key)
        else:
            varname = self.refstr.partition("$")[2]
            varname = varname.partition(':')[0]
            val = self.vars.resolve(varname)

        if val is None:
            return

        return self.apply_renderer_function(val)


class PropertyCache(object):

    def __init__(self):
        self._property_cache_data = {}

    def merge(self, cache):
        if type(cache) != self.__class__:
            log.error("attempt to merge cache failed - provided cache is not "
                      "a %s", type(self.__class__.__name__))
            return

        self._property_cache_data.update(cache.data)

    @property
    def id(self):
        return id(self)

    def set(self, key, data):
        log.debug("%s: caching key=%s with value=%s", id(self), key, data)
        _current = self._property_cache_data.get(key)
        if _current and type(_current) == dict and type(data) == dict:
            self._property_cache_data[key].update(data)
        else:
            self._property_cache_data[key] = data

    @property
    def data(self):
        return self._property_cache_data

    def __getattr__(self, key):
        log.debug("%s: fetching key=%s (exists=%s)", self.id, key,
                  key in self.data)
        if key in self.data:
            return self.data[key]


class YPropertyBase(object):

    def __init__(self, *args, **kwargs):
        whoami = self.__class__.__name__
        log.debug("YPropertyBase %s %s (%s)", args, kwargs, whoami)
        self._cache = PropertyCache()
        super().__init__(*args, **kwargs)

    @property
    def cache(self):
        """
        All properties get their own cache object that they can use as they
        wish.
        """
        return self._cache

    def _load_from_import_cache(self, key):
        """ Retrieve from global context if one exists.

        @param key: key to retrieve
        """
        if not self.context:
            log.info("context not available - cannot load '%s'")
            return

        # we save all imports in a dict called "import_cache" within the
        # global context so that all properties have access.
        c = getattr(self.context, 'import_cache')
        if c:
            return c.get(key)

    def _add_to_import_cache(self, key, value):
        """ Save in the global context if one exists.

        @param key: key to save
        @param value: value to save
        """
        if not self.context:
            log.info("context not available - cannot save '%s'")
            return

        c = getattr(self.context, 'import_cache')
        if c:
            c[key] = value
        else:
            c = {key: value}
            setattr(self.context, 'import_cache', c)

    def get_cls(self, import_str):
        ret = self._load_from_import_cache(import_str)
        if ret:
            log.debug("instantiating class %s (from_cache=True)", import_str)
            return ret

        log.debug("instantiating class %s (from_cache=False)", import_str)
        mod = import_str.rpartition('.')[0]
        class_name = import_str.rpartition('.')[2]
        try:
            ret = getattr(importlib.import_module(mod), class_name)
        except Exception:
            log.exception("failed to import class %s from %s", class_name, mod)
            raise

        self._add_to_import_cache(import_str, ret)
        return ret

    def get_property(self, import_str):
        ret = self._load_from_import_cache(import_str)
        if ret:
            log.debug("calling property %s (from_cache=True)", import_str)
            return ret

        log.debug("calling property %s (from_cache=False)", import_str)
        cls = self.get_cls(import_str.rpartition('.')[0])
        key = "{}.object".format(cls)
        cls_inst = self._load_from_import_cache(key)
        if not cls_inst:
            cls_inst = cls()
            self._add_to_import_cache(key, cls_inst)

        property = import_str.rpartition('.')[2]
        try:
            ret = getattr(cls_inst, property)
        except Exception:
            log.exception("failed to import and call property %s",
                          import_str)

            raise

        self._add_to_import_cache(import_str, ret)
        return ret

    def get_method(self, import_str):
        log.debug("calling method %s", import_str)
        mod = import_str.rpartition('.')[0]
        property = import_str.rpartition('.')[2]
        class_name = mod.rpartition('.')[2]
        mod = mod.rpartition('.')[0]
        cls = getattr(importlib.import_module(mod), class_name)
        try:
            ret = getattr(cls(), property)()
        except Exception:
            log.exception("failed to import and call method %s",
                          import_str)
            raise

        return ret

    def get_attribute(self, import_str):
        log.debug("fetching attribute %s", import_str)
        mod = import_str.rpartition('.')[0]
        attr = import_str.rpartition('.')[2]
        try:
            ret = getattr(importlib.import_module(mod), attr)
        except Exception as exc:
            log.exception("failed to get module attribute %s", import_str)

            # ystruct.YStructOverrideBase swallows AttributeError so need to
            # convert to something else.
            if type(exc) == AttributeError:
                raise ImportError from exc

            raise

        return ret

    def get_import(self, import_str):
        """
        First attempt to treat import string as a class property then try
        module attribute.
        """
        try:
            return self.get_property(import_str)
        except Exception:
            log.exception("get_property failed, trying get_attribute")

        return self.get_attribute(import_str)


class YPropertyOverrideBase(YPropertyBase, YStructOverrideBase):
    pass


class YPropertyMappedOverrideBase(YPropertyBase, YStructMappedOverrideBase):
    pass


class LogicalCollectionHandler(abc.ABC):
    VALID_GROUP_KEYS = ['and', 'or', 'nand', 'nor', 'xor', 'not']
    FINAL_RESULT_OP = 'and'

    @abc.abstractmethod
    def run_single(self, item_list):
        """ run a list i.e. ungrouped. """

    def get_item_result_callback(self, item):
        """
        Implement this if needed.
        """
        raise NotImplementedError

    def group_results(self, logical_op_group):
        results = []
        for item in logical_op_group.members:
            for entry in item:
                try:
                    results.append(self.get_item_result_callback(entry))
                except NotImplementedError:
                    results.append(entry())

        log.debug("group results: %s", results)
        return results

    def run_level(self, level):
        final_results = []
        for item in level:
            final_results.extend(self.run_op_groups(item))
            for subitem in item:
                if subitem._override_name not in self.VALID_GROUP_KEYS:
                    final_results.extend(self.run_single(subitem))

        return final_results

    def run_logical_op_group(self, logical_op_group):
        if logical_op_group._override_name == 'and':
            results = self.group_results(logical_op_group)
            result = all(results)
            log.debug("applied AND(%s) (result=%s)", results, result)
        elif logical_op_group._override_name == 'or':
            results = self.group_results(logical_op_group)
            result = any(results)
            log.debug("applied OR(%s) (result=%s)", results, result)
        elif logical_op_group._override_name in ['nand', 'not']:
            results = self.group_results(logical_op_group)
            result = not all(results)
            log.debug("applied NOT(AND((%s)) (result=%s)", results, result)
        elif logical_op_group._override_name == 'nor':
            results = self.group_results(logical_op_group)
            result = not any(results)
            log.debug("applied NOT(OR((%s)) (result=%s)", results, result)
        else:
            raise Exception("unknown logical operator '{}' found".
                            format(logical_op_group._override_name))

        return result

    def run_op_groups(self, item):
        final_results = []
        for op in self.VALID_GROUP_KEYS:
            op_group = getattr(item, op)
            if op_group:
                result = self.run_logical_op_group(op_group)
                if result is not None:
                    final_results.append(result)

        log.debug("op groups result: %s", final_results)
        return final_results

    def run_collection(self):
        log.debug("run_collection:start (%s)", self._override_name)
        all_results = self.run_level(self)
        log.debug("all_results: %s", all_results)
        result = all(all_results)
        log.debug("final result=%s", result)
        log.debug("run_collection:end (%s)", self._override_name)
        return result
