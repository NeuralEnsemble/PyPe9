"""

  This package combines the common.ncml with existing pyNN classes

  @file ncml.py
  @author Tom Close

"""

#######################################################################################
#
#    Copyright 2012 Okinawa Institute of Science and Technology (OIST), Okinawa, Japan
#
#######################################################################################
from __future__ import absolute_import
import numpy
from neuron import h, nrn, load_mechanisms
from nineline.cells.build.neuron import build_celltype_files
import nineline.cells
from .. import create_unit_conversions, convert_units

basic_nineml_translations = {'Voltage': 'v', 'Diameter': 'diam', 'Length':'L'}

import logging

logger = logging.getLogger("NineLine")

_basic_SI_to_neuron_conversions = (('s', 'ms'),
                                   ('V', 'mV'),
                                   ('A', 'nA'),
                                   ('S', 'uS'),
                                   ('F', 'nF'),
                                   ('m', 'um'),
                                   ('Hz', 'Hz'),
                                   ('Ohm', 'MOhm'),
                                   ('M', 'mM'))

_compound_SI_to_neuron_conversions = (((('A', 1), ('m', -2)), (('mA', 1), ('cm', -2))),
                                    ((('F', 1), ('m', -2)), (('uF', 1), ('cm', -2))),
                                    ((('S', 1), ('m', -2)), (('S', 1), ('cm', -2))),
                                    ((('Ohm', 1), ('m', 1)), (('Ohm', 1), ('cm', 1))))


_basic_unit_dict, _compound_unit_dict = create_unit_conversions(_basic_SI_to_neuron_conversions,
                                                                _compound_SI_to_neuron_conversions)



def convert_to_neuron_units(value, unit_str):
    return convert_units(value, unit_str, _basic_unit_dict, _compound_unit_dict)


class _BaseNineCell(nineline.cells.NineCell):

    class Segment(nrn.Section): #@UndefinedVariable
        """
        Wraps the basic NEURON section to allow non-NEURON attributes to be added to the segment.
        Additional functionality could be added as needed
        """
    
        class ComponentTranslator(object):
            """
            Acts as a proxy for the true component that was inserted using NEURON's in built 'insert' 
            method. Used as a way to avoid the unique-identifier prefix that is prepended to NeMo 
            parameters, while allowing the cellname prefix to be dropped from the component, thus 
            providing a cleaner interface
            """
            def __init__(self, component, translations):
                ## The true component object that was created by the pyNEURON 'insert' method
                super(_BaseNineCell.Segment.ComponentTranslator, self).__setattr__('_component', 
                                                                                   component)
                ## The translation of the parameter names            
                super(_BaseNineCell.Segment.ComponentTranslator, self).__setattr__('_translations', 
                                                                                  translations)
        
            def __setattr__(self, var, value):
                try:
                    setattr(self._component, self._translations[var], value)
                except KeyError as e:
                    raise AttributeError("Component does not have translation for parameter '{}'"\
                                         .format(e))
    
            def __getattr__(self, var):
                try:
                    return getattr(self._component, self._translations[var])
                except KeyError as e:
                    raise AttributeError("Component does not have translation for parameter '{}'"\
                                         .format(e))
                    
            def __dir__(self):
                return (super(_BaseNineCell.Segment.ComponentTranslator, self).__dir__ + 
                        self._translations.keys())
    
        def __init__(self, nineml_model):
            """
            Initialises the Segment including its proximal and distal sections for connecting child 
            segments
            
            @param seg [common.ncml.MorphMLHandler.Segment]: Segment tuple loaded from MorphML \
                                                             (see common.ncml.MorphMLHandler)
            """
            nrn.Section.__init__(self) #@UndefinedVariable
            h.pt3dclear(sec=self)
            self.diam = float(nineml_model.distal.diameter)
            self._distal = numpy.array((nineml_model.distal.x, nineml_model.distal.y, 
                                        nineml_model.distal.z))
            h.pt3dadd(nineml_model.distal.x, nineml_model.distal.y, nineml_model.distal.z,
                      nineml_model.distal.diameter, sec=self)
            if nineml_model.proximal:
                self._set_proximal((nineml_model.proximal.x, nineml_model.proximal.y,
                                    nineml_model.proximal.z))
            # A list to store any gap junctions in
            self._gap_junctions = []
            # Local information, though not sure if I need this here
            self.name = nineml_model.name
            self._parent_seg = None
            self._fraction_along = None
            self._children = []
    
        def __getattr__(self, var):
            """
            Any '.'s in the attribute var are treated as delimeters of a nested varspace lookup. This 
            is done to allow pyNN's population.tset method to set attributes of cell components.
            
            @param var [str]: var of the attribute or '.' delimeted string of segment, component and \
                              attribute vars
            """
            if '.' in var:
                components = var.split('.', 1)
                return getattr(getattr(self, components[0]), components[1])
            else:
                return getattr(self(0.5), var)
    
        def __setattr__(self, var, val):
            """
            Any '.'s in the attribute var are treated as delimeters of a nested varspace lookup.
            This is done to allow pyNN's population.tset method to set attributes of cell components.
            
            @param var [str]: var of the attribute or '.' delimeted string of segment, component and \
                              attribute vars
            @param val [*]: val of the attribute
            """
            if '.' in var:
                components = var.split('.', 1)
                setattr(getattr(self, components[0]), components[1], val)
            else:
                super(_BaseNineCell.Segment, self).__setattr__(var, val)
    
        def _set_proximal(self, proximal):
            """
            Sets the proximal position and calculates the length of the segment
            
            @param proximal [float(3)]: The 3D position of the start of the segment
            """
            self._proximal = numpy.asarray(proximal)
            h.pt3dadd(proximal[0], proximal[1], proximal[2], self.diam, sec=self)
    
        def _connect(self, parent_seg, fraction_along):
            """
            Connects the segment with its parent, setting its proximal position and calculating its
            length if it needs to.
            
            @param parent_seg [Segment]: The parent segment to connect to
            @param fraction_along [float]: The fraction along the parent segment to connect to
            """
            assert(fraction_along >= 0.0 and fraction_along <= 1.0)
            # Connect the segments in NEURON using h.Section's built-in method.
            self.connect(parent_seg, fraction_along, 0)
            # Store the segment's parent just in case
            self._parent_seg = parent_seg
            self._fraction_along = fraction_along
            parent_seg._children.append(self)
    
        def insert(self, component_name, biophysics_name=None, translations=None):
            """
            Inserts a mechanism using the in-built NEURON 'insert' method and then constructs a 
            'Component' class to point to the variable parameters of the component using meaningful 
            names
            
            @param component_name [str]: The name of the component to be inserted
            @param biophysics_name [str]: If the biophysics_name is provided, then it is used as a prefix to the \
                                  component (eg. if biophysics_name='Granule' and component_name='CaHVA', the \
                                  insert mechanism would be 'Granule_CaHVA'), in line with the naming \
                                  convention used for NCML mechanisms
            """
            # Prepend the biophysics_name to the component name if provided
            if biophysics_name:
                mech_name = biophysics_name + "_" + component_name
            else:
                mech_name = component_name
            # Insert the mechanism into the segment
            super(_BaseNineCell.Segment, self).insert(mech_name)
            # Map the component (always at position 0.5 as a segment only ever has one "NEURON segment") 
            # to an object in the Segment object. If translations are provided, wrap the component in
            # a Component translator that intercepts getters and setters and redirects them to the 
            # translated values.
            if translations:
                super(_BaseNineCell.Segment, self).__setattr__(component_name,
                            self.ComponentTranslator(getattr(self(0.5), mech_name), translations))
            else:
                super(_BaseNineCell.Segment, self).__setattr__(component_name, getattr(self(0.5), 
                                                                                       mech_name))
                
    def __init__(self, **parameters):
        self._construct_morphology(self.nineml_model.morphology)
        self._map_biophysics_to_morphology(self.nineml_model)
        # Setup variables required by pyNN
        self.source = self.source_section(0.5)._ref_v
        # for recording
        self.recordable = {'spikes': None, 'v': self.source_section._ref_v} # Once NEST supports sections, it might be an idea to drop this in favour of a more explicit scheme
        for seg_name, seg in self.segments.iteritems():
            self.recordable['{' + seg_name + '}v'] = seg._ref_v 
        self.spike_times = h.Vector(0)
        self.traces = {}
        self.gsyn_trace = {}
        self.recording_time = 0
        self.rec = h.NetCon(self.source, None, sec=self.source_section)
        # Set up references from parameter names to internal variables and set parameters
        self._link_parameters(self.nineml_model)
        self.set_parameters(parameters)
         
    def _construct_morphology(self, nineml_model):
        """
        Reads morphology from a MorphML 2 file and creates the appropriate segments in neuron
        
        @param barebones_only [bool]: If set, extra helper fields will be deleted after the are \
                                      required, leaving the "barebones" pyNEURON structure for \
                                      each nrn.Section
        """
        if not len(nineml_model.segments):
            raise Exception("The loaded morphology does not contain any segments")
        # Initialise all segments
        self.segments = {}
        self.source_section = None
        for model in nineml_model.segments.values():
            seg = _BaseNineCell.Segment(model)
            self.segments[model.name] = seg
            #TODO This should really be part of the 9ML package
            if not model.parent:
                if self.source_section:
                    raise Exception("Two segments ({0} and {1}) were declared without parents, " 
                                    "meaning the neuronal tree is disconnected"
                                    .format(self.source_section.name, seg.name))
                self.source_section = seg
        #TODO And this check too
        if not self.source_section:
            raise Exception("The neuronal tree does not have a root segment, meaning it is " 
                            "connected in a circle (I assume this is not intended)")
        # Connect the segments together
        for model in nineml_model.segments.values():
            if model.parent:
                self.segments[model.name]._connect(self.segments[model.parent.segment_name],
                                                   model.parent.fraction_along)
        # Work out the segment lengths properly accounting for the "fraction_along". This is 
        # performed via a tree traversal to ensure that the parents 'proximal' field has already 
        # been calculated beforehand
        segment_stack = [self.source_section]
        while len(segment_stack):
            seg = segment_stack.pop()
            if seg._parent_seg:
                proximal = (seg._parent_seg._proximal * (1 - seg._fraction_along) + 
                            seg._parent_seg._distal * seg._fraction_along)
                seg._set_proximal(proximal)
            segment_stack += seg._children
        # Set up segment classifications for inserting mechanisms
        self.classifications = {}
        for model in nineml_model.classifications.values():
            classification = {}
            for name, cls_model in model.classes.iteritems(): #@UnusedVariable
                seg_class = []
                for member in cls_model:
                    try:
                        seg_class.append(self.segments[member.segment_name])
                    except KeyError:
                        raise Exception("Member '{}' (referenced in group '{}') was not found in "
                                        "loaded segments".format(member, cls_model.name))
                classification[cls_model.name] = seg_class
            self.classifications[model.name] = classification
                
    def _map_biophysics_to_morphology(self, nineml_model):
        """
        Loop through loaded currents and synapses, and insert them into the relevant sections.
        """
        for mapping in nineml_model.mappings:
            for comp_name in mapping.components:
                component = nineml_model.biophysics.components[comp_name]
                if component.type == 'membrane-capacitance':
                    cm = convert_to_neuron_units(float(component.parameters['C_m'].value),
                                                 component.parameters['C_m'].unit)[0]
                    for seg_class in mapping.segments:
                        for seg in self.classifications[mapping.segments.classification][seg_class]:
                            seg.cm = cm
                elif component.type == 'defaults':
                    Ra = convert_to_neuron_units(float(component.parameters['Ra'].value),
                                                 component.parameters['Ra'].unit)[0]
                    for seg_class in mapping.segments:
                        for seg in self.classifications[mapping.segments.classification][seg_class]:
                            seg.Ra = Ra
                elif component.type == 'post-synaptic-conductance':
                    hoc_name = nineml_model.biophysics.name + '_' + comp_name
                    if hoc_name in dir(h):
                        SynapseType = getattr(h, hoc_name)
                    else:
                        raise Exception("Did not find '{}' synapse type".format(hoc_name))
                    for seg_class in mapping.segments:
                        for seg in self.classifications[mapping.segments.classification][seg_class]:
                            receptor = SynapseType(0.5, sec=seg)
                            setattr(seg, comp_name, receptor)
                else:
                    if self.component_translations.has_key(comp_name):
                        translations = dict([(key, val[0]) for key, val in
                                             self.component_translations[comp_name].iteritems()])
                    else:
                        translations = None
                    for seg_class in mapping.segments:
                        for seg in self.classifications[mapping.segments.classification][seg_class]:
                            try:
                                seg.insert(comp_name, 
                                           biophysics_name=nineml_model.biophysics.name,
                                           translations=translations)
                            except ValueError as e:
                                raise Exception("Could not insert {mech} into section group {clss} "
                                                "({error})".format(mech=comp_name, error=e, 
                                                                   clss=seg_class))
        try:
            ra_param = nineml_model.biophysics.components['__NO_COMPONENT__'].parameters['Ra']
        except KeyError:
            raise Exception("Axial resistance was not set for celltype '{}'"
                            .format(nineml_model.name))
        axial_resistance = convert_to_neuron_units(ra_param.value, ra_param.unit)[0]
        try:
            cm_param = nineml_model.biophysics.components['__NO_COMPONENT__'].parameters['C_m']
        except KeyError:
            raise Exception("Membrane capacitance was not set for celltype '{}'"
                            .format(nineml_model.name))
        capacitance = convert_to_neuron_units(cm_param.value, cm_param.unit)[0]
        for seg in self.segments.values():
            seg.Ra = axial_resistance
            seg.cm = capacitance

    def get_threshold(self):
        return self.nineml_model.biophysics.components['__NO_COMPONENT__'].parameters['V_t'].value


class NineCell(_BaseNineCell):
    
    class Parameter(object):
        
        def __init__(self, name, varname, components):
            self.name = name
            self.varname = varname
            self.components = components
            
        def set(self, value):
            for comp in self.components:
                setattr(comp, self.varname, value)
                
        def get(self):
            if self.components:
                value = getattr(self.components[0], self.varname) 
                for comp in self.components:
                    if value != getattr(comp, self.varname):
                        raise Exception("Found inconsistent values for parameter '{}' ({} and {})"
                                        "across mapped segments"
                                        .format(self.name, value, getattr(comp, self.varname)))
            else:
                raise Exception("Parameter '{}' does not map to any segments ".format(self.name))
            return value        
        
    class InitialState(object):
        
        def __init__(self, name, varname, components):
            self.name = name
            self.varname = varname
            self.components = components
            self.value = None
            self._initialized = False
            
        def set(self, value):
            if self._initialized:
                raise Exception("Attempted to set initial state '{}' after the cell states have " 
                                "been initialised".format(self.name))
            self.value = value
            
        def initialize_state(self):
            for comp in self.components:
                setattr(comp, self.varname, self.value)
            self._initialized = True
            
        def get(self):
            if self.value is None:
                logger.warning("Tried to retrieve value of initial state '{}' before it was set"
                               .format(self.varname))
            return self.value

    def _link_parameters(self, nineml_model):
        self._parameters = {}
        for p in nineml_model.parameters:
            if hasattr(self, p.name) and not self.param_links_tested:
                logger.warning("Naming conflict between parameter '{}' and class member of the same"
                               " name. Parameter can be set but will not be able to be retrieved "
                               "except indirectly through the 'segments' attribute. Please consider"
                               " selecting a different name if possible."
                               .format(p.name))
            try:
                varname = basic_nineml_translations[p.reference]
            except KeyError:
                varname = p.reference
            components = []
            for seg_class in p.segments:
                segments = self.classifications[p.segments.classification][seg_class]
                if p.component:
                    class_components = [getattr(seg, p.component) for seg in segments]
                else:
                    class_components = segments
            components.extend(class_components)
            ParamClass = self.InitialState if p.type == 'initialState' else self.Parameter
            self._parameters[p.name] = ParamClass(p.name, varname, components)
        self.__class__._param_links_tested = True
        
    def set_parameters(self, parameters):
        for name, value in parameters.iteritems():
            try:
                self._parameters[name].set(value)
            except KeyError:
                raise Exception("NineLine celltype '{}' does not have parameter '{}'"
                                .format(type(self), name))
    
    def __getattr__(self, varname):
        """
        To support the access to components on particular segments in PyNN the segment name can 
        be prepended enclosed in curly brackets (i.e. '{}').
         
        @param var [str]: var of the attribute, with optional segment segment name enclosed with {} and prepended
        """
        # Retrieving the _parameters attribute with __getattribute__ first avoids infinite recursive
        # loops of __getattr__ if the cell hasn't been initialised yet.
        parameters = self.__getattribute__('_parameters')
        try:
            return parameters[varname].get()
        except KeyError:
            if varname.startswith('{'):
                seg_name, comp_name = varname[1:].split('}', 1)
                return getattr(self.segments[seg_name], comp_name)
            else:
                raise AttributeError(varname)

    def __setattr__(self, varname, val):
        """
        Any '.'s in the attribute var are treated as delimeters of a nested varspace lookup.
         This is done to allow pyNN's population.tset method to set attributes of cell components.
        
        @param var [str]: var of the attribute or '.' delimeted string of segment, component and \
                          attribute vars
        @param val [*]: val of the attribute
        """
        # Check to see if cell has the '_parameters' attribute, which is initialised last out of the
        # internal member variables, after which the cell is assumed to be initialised and only 
        # parameters can be set as attributes.
        try:
            parameters = self.__getattribute__('_parameters')
        except AttributeError:
            super(NineCell, self).__setattr__(varname, val)
            return
        # If the varname is a parameter
        if parameters.has_key(varname):
            parameters[varname].set(val)
        # Any attribute that ends with '_init' is assumed to be an initial state (this is how PyNN 
        # sets neuron initial states)
        elif varname.endswith('_init'):
            try:
                parameter = parameters[varname[:-5]]
            except KeyError:
                raise Exception("Cell does not have initial state '{}' (as specified by attempting "
                                "to set '{}' on the cell)".format(varname[:-5], varname))
            if not isinstance(parameter, self.InitialState): 
                raise Exception("Parameter '{}' is not an initial state (as specified by attempting"
                                " to set '{}' on the cell)" .format(varname[:-5], varname))
            parameter.set(val)
        # Component parameters can also be directly accessed (without the need to specify them 
        # explicitly as a parameter) by placing the segment name in brackets beforehand, then using
        # a '.' to separate the component name from the parameter name if required, i.e. 
        #
        # {segment}component.parameter for a parameter of a component
        #
        # or 
        # 
        # {segment}parameter for a parameter of the segment directly
        #
        elif varname.startswith('{'): 
            seg_name, comp_name = varname[1:].split('}', 1)
            setattr(self.segments[seg_name], comp_name, val)
        else:
            # TODO: Need to work out if I want this to throw an error or not.
            super(NineCell, self).__setattr__(varname, val)
#             raise Exception("Cannot add new attribute '{}' to cell {} class".format(varname, 
#                                                                                     type(self)))
                
    def __dir__(self):
        return dir(super(_BaseNineCell, self)) + self._parameters.keys()
        
    def memb_init(self):
        for param in self._parameters.itervalues():
            if isinstance(param, self.InitialState):
                param.initialize_state()


class NineCellStandAlone(_BaseNineCell):
    
    def __getattr__(self, varname):
        """
        To support the access to components on particular segments in PyNN the segment name can 
        be prepended enclosed in curly brackets (i.e. '{}').
         
        @param var [str]: var of the attribute, with optional segment segment name enclosed with {} and prepended
        """
        if varname.startswith('{'):
            seg_name, comp_name = varname[1:].split('}', 1)
            return getattr(self.segments[seg_name], comp_name)
        else:
            super(NineCellStandAlone, self).__getattr__(varname) 

    def __setattr__(self, varname, val):
        """
        Any '.'s in the attribute var are treated as delimeters of a nested varspace lookup.
         This is done to allow pyNN's population.tset method to set attributes of cell components.
        
        @param var [str]: var of the attribute or '.' delimeted string of segment, component and \
                          attribute vars
        @param val [*]: val of the attribute
        """
        # Component parameters can also be directly accessed (without the need to specify them 
        # explicitly as a parameter) by placing the segment name in brackets beforehand, then using
        # a '.' to separate the component name from the parameter name if required, i.e. 
        #
        # {segment}component.parameter for a parameter of a component
        #
        # or 
        # 
        # {segment}parameter for a parameter of the segment directly
        #
        if varname.startswith('{'): 
            seg_name, comp_name = varname[1:].split('}', 1)
            setattr(self.segments[seg_name], comp_name, val)
        else:
            super(NineCellStandAlone, self).__setattr__(varname, val)
            
    def _record(self, variable, new_ids):
        """Add the cells in `new_ids` to the set of recorded cells."""
        if variable == 'spikes':
            for id in new_ids:
                if id._cell.rec is not None:
                    id._cell.rec.record(id._cell.spike_times)
        else:
            for id in new_ids:
                self._record_state_variable(id._cell, variable)

    def _record_state_variable(self, cell, variable):
        if hasattr(cell, 'recordable') and variable in cell.recordable:
            hoc_var = cell.recordable[variable]
        elif variable == 'v':
            hoc_var = cell.source_section(0.5)._ref_v  # or use "seg.v"?
        elif variable == 'gsyn_exc':
            hoc_var = cell.esyn._ref_g
        elif variable == 'gsyn_inh':
            hoc_var = cell.isyn._ref_g
        else:
            source, var_name = self._resolve_variable(cell, variable)
            hoc_var = getattr(source, "_ref_%s" % var_name)
        cell.traces[variable] = vec = h.Vector()
        vec.record(hoc_var)
        if not cell.recording_time:
            cell.record_times = h.Vector()
            cell.record_times.record(h._ref_t)
            cell.recording_time += 1

    #could be staticmethod
    def _resolve_variable(self, cell, variable_path):
        match = recordable_pattern.match(variable_path)
        if match:
            parts = match.groupdict()
            if parts['section']:
                section = getattr(cell, parts['section'])
                if parts['location']:
                    source = section(float(parts['location']))
                else:
                    source = section
            else:
                source = cell.source
            return source, parts['var']
        else:
            raise AttributeError("Recording of %s not implemented." % variable_path)

    def reset_recordings(self):
        """Reset the list of things to be recorded."""
        for id in set.union(*self.recorded.values()):
            id._cell.traces = {}
            id._cell.spike_times = h.Vector(0)
        id._cell.recording_time == 0
        id._cell.record_times = None
        for id in set.union(*self.recorded.values()):
            for variable in id._cell.traces:
                id._cell.traces[variable].resize(0)
            id._cell.spike_times.resize(0)      
    
    def record_v(self, active):
        if active:
            self.vtrace = h.Vector()
            self.vtrace.record(self.source_section(0.5)._ref_v)
            if not self.recording_time:
                self.record_times = h.Vector()
                self.record_times.record(h._ref_t)
                self.recording_time += 1
        else:
            self.vtrace = None
            self.recording_time -= 1
            if self.recording_time == 0:
                self.record_times = None

    def record_gsyn(self, syn_name, active):
        # how to deal with static and T-M synapses?
        # record both and sum?
        if active:
            self.gsyn_trace[syn_name] = h.Vector()
            self.gsyn_trace[syn_name].record(getattr(self, syn_name)._ref_g)
            if not self.recording_time:
                self.record_times = h.Vector()
                self.record_times.record(h._ref_t)
                self.recording_time += 1
        else:
            self.gsyn_trace[syn_name] = None
            self.recording_time -= 1
            if self.recording_time == 0:
                self.record_times = None

    def record_spikes(self, active):
        """
        Simple remapping of record onto record_spikes as well
        
        @param active [bool]: Whether the recorder is active or not (required by pyNN)
        """
        if active:
            self.rec = h.NetCon(self.source, None, sec=self.source_section)
            self.rec.record(self.spike_times)
        else:
            self.spike_times = h.Vector(0)
    

class NineCellMetaClass(nineline.cells.NineCellMetaClass):
    """
    Metaclass for building NineMLNineCellType subclasses
    Called by nineml_celltype_from_model
    """

    loaded_celltypes = {}

    def __new__(cls, celltype_name, nineml_model, build_mode='lazy', silent=False, solver_name=None,
                standalone=True): #@UnusedVariable
        opt_args = (solver_name, standalone)
        try:
            celltype = cls.loaded_celltypes[(nineml_model.name, nineml_model.url, opt_args)]
        except KeyError:
            dct = {'nineml_model': nineml_model}
            build_options = nineml_model.biophysics.build_hints['nemo']['neuron']
            install_dir, dct['component_translations'] = \
                    build_celltype_files(nineml_model.biophysics.name, nineml_model.url, 
                                         build_mode=build_mode,
                                         method=build_options.method, 
                                         kinetics=build_options.kinetic_components,
                                         silent_build=silent)
            load_mechanisms(install_dir)
            dct['mech_path'] = install_dir
            dct['_param_links_tested'] = False
            if standalone:
                BaseClass = NineCellStandAlone
            else:
                BaseClass = NineCell
            celltype = super(NineCellMetaClass, cls).__new__(cls, celltype_name, nineml_model, 
                                                             (BaseClass,), dct)
            # Save cell type in case it needs to be used again
            cls.loaded_celltypes[(celltype_name, nineml_model.url, opt_args)] = celltype
        return celltype


if __name__ == "__main__":
    pass

