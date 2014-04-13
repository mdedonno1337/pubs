import shutil
import glob
import itertools

from . import bibstruct
from . import events
from . import datacache
from .paper import Paper

def _base27(n):
    return _base27((n - 1) // 26) + chr(ord('a') + ((n - 1) % 26)) if n else ''


class CiteKeyCollision(Exception):
    pass


class InvalidReference(Exception):
    pass


class Repository(object):

    def __init__(self, config):
        self.config = config
        self._citekeys = None
        self.databroker = datacache.DataCache(self.config.pubsdir)

    @property
    def citekeys(self):
        if self._citekeys is None:
            self._citekeys = self.databroker.citekeys()
        return self._citekeys

    def __contains__(self, citekey):
        """ Allows to use 'if citekey in repo' pattern

            Warning: costly the first time.
        """
        return citekey in self.citekeys

    def __len__(self):
        """Warning: costly the first time."""
        return len(self.citekeys)

    # papers
    def all_papers(self):
        for key in self.citekeys:
            yield self.pull_paper(key)

    def pull_paper(self, citekey):
        """Load a paper by its citekey from disk, if necessary."""
        if self.databroker.exists(citekey, both = True):
            return Paper(self.databroker.pull_bibdata(citekey),
                         citekey=citekey,
                         metadata=self.databroker.pull_metadata(citekey))
        else:
            raise InvalidReference('{} citekey not found'.format(citekey))

    def push_paper(self, paper, overwrite=False, event=True):
        """ Push a paper to disk

            :param overwrite:  if False, mimick the behavior of adding a paper
                               if True, mimick the behavior of updating a paper
        """
        bibstruct.check_citekey(paper.citekey)
        if (not overwrite) and self.databroker.exists(paper.citekey, both = False):
            raise IOError('files using the {} citekey already exists'.format(paper.citekey))
        if (not overwrite) and self.citekeys is not None and paper.citekey in self.citekeys:
            raise CiteKeyCollision('citekey {} already in use'.format(paper.citekey))

        self.databroker.push_bibdata(paper.citekey, paper.bibdata)
        self.databroker.push_metadata(paper.citekey, paper.metadata)
        self.citekeys.add(paper.citekey)
        if event:
            events.AddEvent(paper.citekey).send()

    def remove_paper(self, citekey, remove_doc=True, event=True):
        """ Remove a paper. Is silent if nothing needs to be done."""

        if event:
            events.RemoveEvent(citekey).send()
        if remove_doc:
            try:
                metadata = self.databroker.pull_metadata(citekey)
                docpath = metadata.get('docfile')
                self.databroker.remove_doc(docpath, silent=True)
                self.databroker.remove_note(citekey, silent=True)
            except IOError:
                pass # FXME: if IOError is about being unable to
                     # remove the file, we need to issue an error.I

        self.citekeys.remove(citekey)
        self.databroker.remove(citekey)

    def rename_paper(self, paper, new_citekey):
        old_citekey = paper.citekey
        # check if new_citekey is not the same as paper.citekey
        if old_citekey == new_citekey:
            push_paper(paper, overwrite=True, event=False)
        else:
            # check if new_citekey does not exists
            if self.databroker.exists(new_citekey, both=False):
                raise IOError("can't rename paper to {}, conflicting files exists".format(new_citekey))

            new_bibdata = {}
            new_bibdata[new_citekey] = paper.bibdata[old_citekey]
            paper.bibdata = new_bibdata

            # move doc file if necessary
            if self.databroker.in_docsdir(paper.docpath):
                paper.docpath = self.databroker.rename_doc(paper.docpath, new_citekey)

            # move note file if necessary
            try:
                self.databroker.rename_note(old_citekey, new_citekey)
            except IOError:
                pass

            # push_paper to new_citekey
            paper.citekey = new_citekey
            self.push_paper(paper, event=False)
            # remove_paper of old_citekey
            self.remove_paper(old_citekey, event=False)
            # send event
            events.RenameEvent(paper, old_citekey).send()

    def unique_citekey(self, base_key):
        """Create a unique citekey for a given basekey."""
        for n in itertools.count():
            if not base_key + _base27(n) in self.citekeys:
                return base_key + _base27(n)

    def get_tags(self):
        """FIXME: bibdata doesn't need to be read."""
        tags = set()
        for p in self.all_papers():
            tags = tags.union(p.tags)
        return tags

