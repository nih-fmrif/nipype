# -*- coding: utf-8 -*-
# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
"""Provide interface to AFNI commands."""
from __future__ import print_function, division, unicode_literals, absolute_import
from builtins import object, str
from future.utils import raise_from

import os, re
from sys import platform
from distutils import spawn

from ... import logging
from ...utils.filemanip import split_filename, fname_presuffix

from ..base import (
    CommandLine, traits, CommandLineInputSpec, isdefined, File, TraitedSpec, ImageFile)
from ...external.due import BibTeX
import traits.api as traits
from traits.trait_errors import TraitError


# Use nipype's logging system
IFLOGGER = logging.getLogger('interface')


class Info(object):
    """Handle afni output type and version information.
    """
    __outputtype = 'NIFTI_GZ'
    ftypes = {'NIFTI': '.nii',
              'AFNI': '',
              'NIFTI_GZ': '.nii.gz'}

    @staticmethod
    def version():
        """Check for afni version on system

        Parameters
        ----------
        None

        Returns
        -------
        version : str
           Version number as string or None if AFNI not found

        """
        try:
            clout = CommandLine(command='afni_vcheck',
                                terminal_output='allatonce').run()

            # Try to parse the version number
            currv = clout.runtime.stdout.split('\n')[1].split('=', 1)[1].strip()
        except IOError:
            # If afni_vcheck is not present, return None
            IFLOGGER.warn('afni_vcheck executable not found.')
            return None
        except RuntimeError as e:
            # If AFNI is outdated, afni_vcheck throws error.
            # Show new version, but parse current anyways.
            currv = str(e).split('\n')[4].split('=', 1)[1].strip()
            nextv = str(e).split('\n')[6].split('=', 1)[1].strip()
            IFLOGGER.warn(
                'AFNI is outdated, detected version %s and %s is available.' % (currv, nextv))

        if currv.startswith('AFNI_'):
            currv = currv[5:]

        v = currv.split('.')
        try:
            v = [int(n) for n in v]
        except ValueError:
            return currv
        return tuple(v)

    @classmethod
    def output_type_to_ext(cls, outputtype):
        """Get the file extension for the given output type.

        Parameters
        ----------
        outputtype : {'NIFTI', 'NIFTI_GZ', 'AFNI'}
            String specifying the output type.

        Returns
        -------
        extension : str
            The file extension for the output type.
        """

        try:
            return cls.ftypes[outputtype]
        except KeyError as e:
            msg = 'Invalid AFNIOUTPUTTYPE: ', outputtype
            raise_from(KeyError(msg), e)

    @classmethod
    def outputtype(cls):
        """AFNI has no environment variables,
        Output filetypes get set in command line calls
        Nipype uses AFNI as default


        Returns
        -------
        None
        """
        # warn(('AFNI has no environment variable that sets filetype '
        #      'Nipype uses NIFTI_GZ as default'))
        return 'NIFTI_GZ'

    @staticmethod
    def standard_image(img_name):
        '''Grab an image from the standard location.

        Could be made more fancy to allow for more relocatability'''
        clout = CommandLine('which afni',
                            terminal_output='allatonce').run()
        if clout.runtime.returncode is not 0:
            return None

        out = clout.runtime.stdout
        basedir = os.path.split(out)[0]
        return os.path.join(basedir, img_name)


class AFNICommandBase(CommandLine):
    """
    A base class to fix a linking problem in OSX and afni.
    See http://afni.nimh.nih.gov/afni/community/board/read.php?1,145346,145347#msg-145347
    """
    def _run_interface(self, runtime):
        if platform == 'darwin':
            runtime.environ['DYLD_FALLBACK_LIBRARY_PATH'] = '/usr/local/afni/'
        return super(AFNICommandBase, self)._run_interface(runtime)


class AFNICommandInputSpec(CommandLineInputSpec):
    outputtype = traits.Enum('AFNI', list(Info.ftypes.keys()),
                             desc='AFNI output filetype')
    out_file = File(name_template="%s_afni", desc='output image file name',
                    argstr='-prefix %s',
                    name_source=["in_file"])


class AFNICommandOutputSpec(TraitedSpec):
    out_file = File(desc='output file',
                    exists=True)

class AFNICommand(AFNICommandBase):
    """Shared options for several AFNI commands """
    input_spec = AFNICommandInputSpec
    _outputtype = None

    references_ = [{'entry': BibTeX('@article{Cox1996,'
                                    'author={R.W. Cox},'
                                    'title={AFNI: software for analysis and '
                                    'visualization of functional magnetic '
                                    'resonance neuroimages},'
                                    'journal={Computers and Biomedical research},'
                                    'volume={29},'
                                    'number={3},'
                                    'pages={162-173},'
                                    'year={1996},'
                                    '}'),
                    'tags': ['implementation'],
                    },
                   {'entry': BibTeX('@article{CoxHyde1997,'
                                    'author={R.W. Cox and J.S. Hyde},'
                                    'title={Software tools for analysis and '
                                    'visualization of fMRI data},'
                                    'journal={NMR in Biomedicine},'
                                    'volume={10},'
                                    'number={45},'
                                    'pages={171-178},'
                                    'year={1997},'
                                    '}'),
                    'tags': ['implementation'],
                    }]

    def __init__(self, **inputs):
        super(AFNICommand, self).__init__(**inputs)
        self.inputs.on_trait_change(self._output_update, 'outputtype')

        if self._outputtype is None:
            self._outputtype = Info.outputtype()

        if not isdefined(self.inputs.outputtype):
            self.inputs.outputtype = self._outputtype
        else:
            self._output_update()

    def _run_interface(self, runtime):
        # Update num threads estimate from OMP_NUM_THREADS env var
        # Default to 1 if not set
        self.inputs.environ['OMP_NUM_THREADS'] = str(self.num_threads)
        return super(AFNICommand, self)._run_interface(runtime)

    def _output_update(self):
        """ i think? updates class private attribute based on instance input
         in fsl also updates ENVIRON variable....not valid in afni
         as it uses no environment variables
        """
        self._outputtype = self.inputs.outputtype

    @classmethod
    def set_default_output_type(cls, outputtype):
        """Set the default output type for AFNI classes.

        This method is used to set the default output type for all afni
        subclasses.  However, setting this will not update the output
        type for any existing instances.  For these, assign the
        <instance>.inputs.outputtype.
        """

        if outputtype in Info.ftypes:
            cls._outputtype = outputtype
        else:
            raise AttributeError('Invalid AFNI outputtype: %s' % outputtype)

    def _overload_extension(self, value, name=None):
        path, base, _ = split_filename(value)
        return os.path.join(path, base + Info.output_type_to_ext(self.inputs.outputtype))

    def _list_outputs(self):
        outputs = super(AFNICommand, self)._list_outputs()
        metadata = dict(name_source=lambda t: t is not None)
        out_names = list(self.inputs.traits(**metadata).keys())
        if out_names:
            for name in out_names:
                if outputs[name]:
                    _, _, ext = split_filename(outputs[name])
                    if ext == "":
                        outputs[name] = outputs[name] + "+orig.BRIK"
        return outputs

    def _gen_fname(self, basename, cwd=None, suffix=None, change_ext=True,
                   ext=None):
        """Generate a filename based on the given parameters.

        The filename will take the form: cwd/basename<suffix><ext>.
        If change_ext is True, it will use the extentions specified in
        <instance>intputs.output_type.

        Parameters
        ----------
        basename : str
            Filename to base the new filename on.
        cwd : str
            Path to prefix to the new filename. (default is os.getcwd())
        suffix : str
            Suffix to add to the `basename`.  (defaults is '' )
        change_ext : bool
            Flag to change the filename extension to the FSL output type.
            (default True)

        Returns
        -------
        fname : str
            New filename based on given parameters.

        """

        if basename == '':
            msg = 'Unable to generate filename for command %s. ' % self.cmd
            msg += 'basename is not set!'
            raise ValueError(msg)
        if cwd is None:
            cwd = os.getcwd()
        if ext is None:
            ext = Info.output_type_to_ext(self.inputs.outputtype)
        if change_ext:
            if suffix:
                suffix = ''.join((suffix, ext))
            else:
                suffix = ext
        if suffix is None:
            suffix = ''
        fname = fname_presuffix(basename, suffix=suffix,
                                use_ext=False, newpath=cwd)
        return fname

    def _parse_inputs(self, skip=None):
        """Parse all inputs using the ``argstr`` format string in the Trait.

        Any inputs that are assigned (not the default_value) are formatted
        to be added to the command line.

        Returns
        -------
        all_args : list
            A list of all inputs formatted for the command line.

        """
        all_args = []
        initial_args = {}
        final_args = {}
        metadata = dict(argstr=lambda t: t is not None)
        for name, spec in sorted(self.inputs.traits(**metadata).items()):
            if skip and name in skip:
                continue
            value = getattr(self.inputs, name)
            if spec.name_source:
                value = self._filename_from_source(name)
            elif spec.genfile:
                if not isdefined(value) or value is None:
                    value = self._gen_filename(name)

            if not isdefined(value):
                continue
            arg = self._format_arg(name, spec, value)
            if arg is None:
                continue
            pos = spec.position
            if pos is not None:
                if int(pos) >= 0:
                    initial_args[pos] = arg
                else:
                    final_args[pos] = arg
            else:
                all_args.append(arg)
        first_args = [arg for pos, arg in sorted(initial_args.items())]
        last_args = [arg for pos, arg in sorted(final_args.items())]
        return first_args + all_args + last_args


def no_afni():
    """ Checks if AFNI is available """
    if Info.version() is None:
        return True
    return False


class AFNIPythonCommandInputSpec(CommandLineInputSpec):
    outputtype = traits.Enum('AFNI', list(Info.ftypes.keys()),
                             desc='AFNI output filetype')
    py27_path = traits.Either('python2', File(exists=True),
        usedefault=True,
        default='python2')

class AFNIPythonCommand(AFNICommand):
    @property
    def cmd(self):
        """Finds the path to the python script, if it can't returns the command"""
        if spawn.find_executable(super(AFNIPythonCommand, self).cmd) is not None:
            return spawn.find_executable(super(AFNIPythonCommand, self).cmd)
        else:
            return super(AFNIPythonCommand, self).cmd

    @property
    def cmdline(self):
        return "{} {}".format(self.inputs.py27_path, super(AFNIPythonCommand, self).cmdline)

class ImageFileAFNI(ImageFile):
    """
    Defines an ImageFile trait specific to AFNI interfaces.

    Files with an optional subbrick selector. Files without an extension
    specified are assumed to have a .HEAD extension.
    Other commandline fanciness will be implmented as interfaces.

    """

    def __init__(self, value='', filter=None, auto_set=False, entries=0,
                 exists=False, types=['nifti1', 'nifti2', 'afni'],
                 allow_compressed=True, **metadata):
    
        self.types = types
        self.allow_compressed = allow_compressed

        super(ImageFileAFNI, self).__init__(value, filter, auto_set, entries,
                                            exists, types, allow_compressed,
                                            **metadata)

    def validate(self, object, name, value):
        """ Validates that a specified value is valid for this trait.
        """
        #maybe clean this up with a regex, but for now, this works

        path, filename = os.path.split(value)
        try:
            ext = re.findall(r'(\.nii\.gz$|\.HEAD$|\.BRIK$|\.nii$)', filename)[0]
            filename = filename[:-len(ext)]
        except IndexError:
            ext = '.HEAD'

        to_validate = path + os.path.sep + filename + ext
        validated_value = super(ImageFileAFNI, self).validate(object, name, to_validate)
        return validated_value
