"""

  This package mirrors the one in pyNN

  @file __init__.py
  @author Tom Close

"""

#######################################################################################
#
#    Copyright 2012 Okinawa Institute of Science and Technology (OIST), Okinawa, Japan
#
#######################################################################################

import os
from collections import namedtuple
import numpy
from ninemlp import SRC_PATH, DEFAULT_BUILD_MODE, pyNN_build_mode
from ninemlp.neuron.build import compile_nmodl
compile_nmodl(os.path.join(SRC_PATH, 'pyNN', 'neuron', 'nmodl'), build_mode=pyNN_build_mode,
              silent=True)
import ninemlp.common
from ninemlp.neuron.ncml import NCMLCell, group_varname, seg_varname
import pyNN.common
import pyNN.core
import pyNN.neuron.standardmodels.cells
import pyNN.neuron.connectors
import pyNN.neuron.recording
import ncml
from pyNN.neuron import setup, run, reset, end, get_time_step, get_current_time, get_min_delay, \
                        get_max_delay, rank, num_processes, record, record_v, record_gsyn, \
                        StepCurrentSource, DCSource, errors, NoisyCurrentSource
#ACSource, 
import pyNN.neuron as sim
from pyNN.common.control import build_state_queries
import pyNN.neuron.simulator as simulator
import neuron
from neuron import h
import logging

logger = logging.getLogger("PyNN")


get_current_time, get_time_step, get_min_delay, \
        get_max_delay, num_processes, rank = build_state_queries(simulator)

class Population(ninemlp.common.Population, pyNN.neuron.Population):

    def __init__(self, label, size, cell_type, params={}, build_mode=DEFAULT_BUILD_MODE):
        """
        Initialises the population after reading the population parameters from file
        @param label: the label assigned to the population (its NINEML id)
        @param size: the size of the population
        @param cell_type: The cell model used to instantiate the population.
        @param params: the parameters passed to the cell model (Note that at this stage the same \
                        parameters are passed to every cell in the model)
        @param build_mode: Specifies whether cell models, or in NEURON's case, cell mechanisms need\
                            to be built. This is actually performed when the cell_type is loaded \
                           but if build_mode is set to 'build_only' then the population isn't \
                           actually constructed and only the NMODL files are compiled.
        """
        if build_mode == 'build_only' or build_mode == 'compile_only':
            print "Warning! '--build' option was set to 'build_only' or 'compile_only', " \
                  "meaning the Population '{}' was not constructed and only the NMODL files " \
                  "were compiled.".format(label)
        else:
            # If cell_type is of NCML type append the population as a parent parameter for its 
            # constructor
            if issubclass(cell_type, NCMLCell):
                params = params.copy()
                params['parent'] = self
            pyNN.neuron.Population.__init__(self, size, cell_type, params, structure=None,
                                            label=label)


    #FIXME: I think this should be deleted
    def set_param(self, cell_id, param, value, component=None, section=None):
        raise NotImplementedError('set_param has not been implemented for Population class yet')

    def rset(self, param, rand_distr, component=None, seg_group=None):
        param_scope = [group_varname(seg_group)]
        if component:
            param_scope.append(component)
        param_scope.append(param)
        pyNN.neuron.Population.rset(self, '.'.join(param_scope), rand_distr)

    def initialize(self, variable, rand_distr, component=None, seg_group=None):
        variable_scope = [group_varname(seg_group)]
        if component:
            variable_scope.append(component)
        variable_scope.append(variable)
        pyNN.neuron.Population.initialize(self, '.'.join(variable_scope), rand_distr)

    def can_record(self, variable):
        """
        Overloads that from pyNN.common.BasePopulation to allow section names and positions to 
        be passed.
        """
        if hasattr(self.celltype, 'ncml_model'): # If cell is generated from NCML file
            match = pyNN.neuron.recording.recordable_pattern.match(variable)
            if match:
                parts = match.groupdict()
                if parts['var'] not in self.celltype.recordable:
                    return False
                if parts['section']: # Check to see if section exists
                    if not hasattr(self.celltype, parts['section']):
                        return False
                if parts.has_key('position'): # Check to see if the position is between 0-1
                    pos = float(parts['position'])
                    if pos < 0.0 or pos > 1.0:
                        raise Exception("Position parameter in recording string, {}, is out of "
                                        "range (0.0-1.0)".format(pos))
                return True
            else:
                raise Exception("Could not parse variable name '%s'" % variable)
        else:
            return pyNN.neuron.Population.can_record(self, variable)


class Projection(pyNN.neuron.Projection):

    def __init__(self, pre, dest, label, connector, source=None, target=None,
                 build_mode=DEFAULT_BUILD_MODE, rng=None):
        self.label = label
        if build_mode == 'build_only' or build_mode == 'compile_only':
            print "Warning! '--build' option was set to 'build_only', meaning the projection " \
                  "'{}' was not constructed.".format(label)
        else:
            pyNN.neuron.Projection.__init__(self, pre, dest, connector, label=label, source=source,
                                            target=target, rng=rng)



class GapJunctionProjection(Projection):

    def __init__(self, pre, dest, label, connector, source_secname=None, target_secname=None, 
                 rng=None):
        """
        ` rectified [bool]: Whether the gap junction is rectified (only one direction)
        """
        ## Start of unique variable-GID range assigned for this projection (ends at gid_count + pre.size * dest.size * 2)
        self.vargid_start = simulator.state.vargid_counter
        # Allocate a range of vargid's for this projection that allows all pre-synaptic cells 
        # to be connected to all post-synaptic cells once. This seems a reasonable to me but 
        # looking at the code the for FixedNumberPostConnector this may not be true in all cases.
        # Any thoughts on how to be more general about this? We could probably use just really big 
        # intervals between projections
        simulator.state.vargid_counter += pre.size * dest.size * 2
        # Stores the connection objects (simulator.GapJunctionConnection) in a dictionary rather than 
        # a list as it is in the Projection class so they can be more easily accessed on the
        # target side.
        self._connections_dict = {}
        self.source_secname = source_secname if source_secname else 'source_section'
        self.target_secname = target_secname if target_secname else 'source_section'
        Projection.__init__(self, pre, dest, label, connector, None, None, rng=rng)

    def _divergent_connect(self, source, targets, weights, delays=None): #@UnusedVariable
        """
        Connect a neuron to one or more other neurons with a static connection.
        
        `source` -- the ID of the pre-synaptic cell [common.IDmixin].
        `targets` -- a list/1D array of post-synaptic cell IDs, or a single ID [list(common.IDmixin)].
        `weights` -- Connection weight(s). Must have the same length as "targets" [list(float) or float].
        `delays` -- This is actually ignored but only included to match the same signature as the Population._divergent_connect method
        """
        if not isinstance(source, int) or source > simulator.state.gid_counter or source < 0:
            errmsg = "Invalid source ID: {} (gid_counter={})".format(source,
                                                                     simulator.state.gid_counter)
            raise errors.ConnectionError(errmsg)
        if not pyNN.core.is_listlike(targets):
            targets = [targets]
        if isinstance(weights, float):
            weights = [weights]
        assert len(targets) > 0
        for target in targets:
            if not isinstance(target, pyNN.common.IDMixin):
                raise errors.ConnectionError("Invalid target ID: {}".format(target))
        assert len(targets) == len(weights), "{} {}".format(len(targets), len(weights))
        vargid_offset = self.pre.id_to_index(source) * len(self.post) * 2 + self.vargid_start
        for target, weight in zip(targets, weights):
            # Get the variable-GIDs (as distinct from the GIDs used for cells) for both the pre to post  
            # connection the post to pre            
            pre_post_vargid = vargid_offset + self.post.id_to_index(target) * 2
            post_pre_vargid = pre_post_vargid + 1
            # Get the segment on target cell the gap junction connects to
            section = getattr(target._cell, self.target_secname)
            # Connect the pre cell voltage to the target var
            logger.info("Setting source_var on target cell {} to connect to source cell {} with "
                        "vargid {} on process {}"
                        .format(target, source, post_pre_vargid, simulator.state.mpi_rank))
            simulator.state.parallel_context.source_var(section(0.5)._ref_v, post_pre_vargid) #@UndefinedVariableFromImport              
            # Create the gap_junction and set its weight
            gap_junction = h.Gap(0.5, sec=section)
            gap_junction.g = weight
            # Connect the gap junction with the source_var
            logger.info("Setting target_var on target cell {} to connect to source cell {} with "
                        "vargid {} on process {}"
                        .format(target, source, pre_post_vargid, simulator.state.mpi_rank))
            simulator.state.parallel_context.target_var(gap_junction._ref_vgap, pre_post_vargid) #@UndefinedVariableFromImport
            # Add target gap mechanism to the dictionary holding the connections so that its 
            # conductance can be changed after construction.
            try:
                self._connections_dict[(source, target)].target_gap = gap_junction
            except KeyError: #If source does not exist on the local node
                self._connections_dict[(source, target)] = simulator.GapJunctionConnection(
                                                               source, target, None, gap_junction)

    def _prepare_sources(self, source, targets, weights, delays=None): #@UnusedVariable
        """
        Connect a neuron to one or more other neurons with a static connection.
        
        `source` -- the ID of the pre-synaptic cell [common.IDmixin].
        `targets` -- a list/1D array of post-synaptic cell IDs, or a single ID [list(common.IDmixin)].
        `weights` -- Connection weight(s). Must have the same length as `targets` [list(float) or float].
        `delays` -- This is actually ignored but only included to match the same signature as the _divergent_connect method
        """
        if not source.local:
            raise Exception("source needs to be local for _divergent_sources")
        if not isinstance(source, int) or source > simulator.state.gid_counter or source < 0:
            errmsg = "Invalid source ID: {} (gid_counter={})".format(source,
                                                                     simulator.state.gid_counter)
            raise errors.ConnectionError(errmsg)
        if not pyNN.core.is_listlike(targets):
            targets = [targets]
        if isinstance(weights, float):
            weights = [weights]
        assert len(targets) > 0
        for target in targets:
            if not isinstance(target, pyNN.common.IDMixin):
                raise errors.ConnectionError("Invalid target ID: {}".format(target))
        assert len(targets) == len(weights), "{} {}".format(len(targets), len(weights))
        # Get the section on the pre cell that the gap junction is connected to
        section = getattr(source._cell, self.source_secname)
        vargid_offset = self.pre.id_to_index(source) * len(self.post) * 2 + self.vargid_start
        for target, weight in zip(targets, weights):
            # Get the variable-GIDs (as distinct from the GIDs used for cells) for both the pre to post  
            # connection the post to pre
            pre_post_vargid = vargid_offset + self.post.id_to_index(target) * 2
            post_pre_vargid = pre_post_vargid + 1
            # Connect the pre cell voltage to the target var
            logger.info("Setting source_var on source cell {} to connect to target cell {} with "
                        "vargid {} on process {}"
                        .format(source, target, pre_post_vargid, simulator.state.mpi_rank))
            simulator.state.parallel_context.source_var(section(0.5)._ref_v, pre_post_vargid) #@UndefinedVariableFromImport                    
            # Create the gap_junction and set its weight
            gap_junction = h.Gap(0.5, sec=section)
            gap_junction.g = weight
            # Connect the gap junction with the source_var
            logger.info("Setting target_var on source cell {} to connect to target cell {} with "
                        "vargid {} on process {}"
                        .format(source, target, post_pre_vargid, simulator.state.mpi_rank))
            simulator.state.parallel_context.target_var(gap_junction._ref_vgap, post_pre_vargid) #@UndefinedVariableFromImport              
            # Store mechanism so that its conductance can be changed after construction
            self._connections_dict[(source, target)] = simulator.GapJunctionConnection(
                                                               source, target, gap_junction)

    def _convergent_connect(self, sources, target, weights, delays):
        raise NotImplementedError

    def _get_connections(self):
        """
        Used to make the connections_dict act like a list so it can be used in Projection
        class functions.
        """
        return self._connections_dict.values()

    def _set_connections(self, c):
        """
        Only allows the dictionary, which pretends to be a list to be set to the empty list.
        Feels a little hackish.
        """
        if len(c):
            raise Exception("Can only initialise connections of GapJunctionProjection to an empty "
                            "list")
        self._connections_dict.clear()

    connections = property(_get_connections, _set_connections)

#    
#
#class ElectricalSynapseProjection(Projection):
#
#    ## A named tuple to hold a record of the generated electrical synapse connections
#    Connection = namedtuple('Connection', 'cell1 segment1 cell2 segment2')
#
#    ## This holds the last reserved GID used to connect the source and target variables. It is incremented each time a Projection is initialised by the amount needed to hold an all-to-all connection
#    gid_count = 0
#
#    def __init__(self, pre, dest, label, connector, source=None, target=None,
#                 build_mode=DEFAULT_BUILD_MODE, rng=None):
#        """
#        @param rectified [bool]: Whether the gap junction is rectified (only one direction)
#        """
#        ## Start of unique variable-GID range assigned for this projection (ends at gid_count + pre.size * dest.size * 2)
#        self.gid_start = self.__class__.gid_count
#        self.__class__.gid_count += pre.size * dest.size * 2
#        Projection.__init__(self, pre, dest, label, connector, source, target, build_mode, rng=rng)
#
#
#    def _divergent_connect(self, source, targets, weights, delays=None): #@UnusedVariable
#        """
#        Connect a neuron to one or more other neurons with a static connection.
#        
#        @param source [pyNN.common.IDmixin]: the ID of the pre-synaptic cell.
#        @param [list(pyNN.common.IDmixin)]: a list/1D array of post-synaptic cell IDs, or a single ID.
#        @param [list(float) or float]: Connection weight(s). Must have the same length as `targets`.
#        @param delays [Null]: This is actually ignored but only included to match the same signature\
# as the Population._divergent_connect method
#        """
#        if not isinstance(source, int) or source > simulator.state.gid_counter or source < 0:
#            errmsg = "Invalid source ID: {} (gid_counter={})".format(source,
#                                                                     simulator.state.gid_counter)
#            raise errors.ConnectionError(errmsg)
#        if not pyNN.core.is_listlike(targets):
#            targets = [targets]
#        if isinstance(weights, float):
#            weights = [weights]
#        assert len(targets) > 0
#        for target in targets:
#            if not isinstance(target, pyNN.common.IDMixin):
#                raise errors.ConnectionError("Invalid target ID: {}".format(target))
#        assert len(targets) == len(weights), "{} {}".format(len(targets), len(weights))
#        # Rename variable that has been repurposed slightly        
#        segname = self.synapse_type
#        gid_offset = self.pre.id_to_index(source) * len(self.post) + self.gid_start
#        for target, weight in zip(targets, weights):
#            # "variable" GIDs (as distinct from the GIDs used for cells) for both the pre to post  
#            # connection the post to pre            
#            pre_post_gid = (gid_offset + self.post.id_to_index(target)) * 2
#            post_pre_gid = pre_post_gid + 1
#            # Get the segment on target cell the gap junction connects to
#            segment = target._cell.segments[segname] if segname else target.source_section
#            # Connect the pre cell voltage to the target var
##            print "Setting source_var on target cell {} to connect to source cell {} with gid {} on process {}".format(target, source, post_pre_gid, simulator.state.mpi_rank)
#            simulator.state.parallel_context.source_var(segment(0.5)._ref_v, post_pre_gid) #@UndefinedVariableFromImport              
#            # Create the gap_junction and set its weight
#            gap_junction = h.Gap(0.5, sec=segment)
#            gap_junction.g = weight
#            # Store gap junction in a list so it doesn't get collected by the garbage 
#            # collector
#            segment._gap_junctions.append(gap_junction)
#            # Connect the gap junction with the source_var
##            print "Setting target_var on target cell {} to connect to source cell {} with gid {} on process {}".format(target, source, pre_post_gid, simulator.state.mpi_rank)
#            simulator.state.parallel_context.target_var(gap_junction._ref_vgap, pre_post_gid) #@UndefinedVariableFromImport
#
#    def _prepare_sources(self, source, targets, weights, delays=None): #@UnusedVariable
#        """
#        Connect a neuron to one or more other neurons with a static connection.
#        
#        @param source [pyNN.common.IDmixin]: the ID of the pre-synaptic cell.
#        @param [list(pyNN.common.IDmixin)]: a list/1D array of post-synaptic cell IDs, or a single ID.
#        @param [list(float) or float]: Connection weight(s). Must have the same length as `targets`.
#        @param delays [Null]: This is actually ignored but only included to match the same signature\
# as the Population._divergent_connect method
#        """
#        if not source.local:
#            raise Exception("source needs to be local for _divergent_sources")
#        if not isinstance(source, int) or source > simulator.state.gid_counter or source < 0:
#            errmsg = "Invalid source ID: {} (gid_counter={})".format(source,
#                                                                     simulator.state.gid_counter)
#            raise errors.ConnectionError(errmsg)
#        if not pyNN.core.is_listlike(targets):
#            targets = [targets]
#        if isinstance(weights, float):
#            weights = [weights]
#        assert len(targets) > 0
#        for target in targets:
#            if not isinstance(target, pyNN.common.IDMixin):
#                raise errors.ConnectionError("Invalid target ID: {}".format(target))
#        assert len(targets) == len(weights), "{} {}".format(len(targets), len(weights))
#        # Get the segment on the pre cell that the gap junction is connected to
#        segment = source._cell.segments[self.source] if self.source else source.source_section
#        gid_offset = self.pre.id_to_index(source) * len(self.post) + self.gid_start
#        for target, weight in zip(targets, weights):
#            # "variable" GIDs (as distinct from the GIDs used for cells) for both the pre to post  
#            # connection the post to pre
#            pre_post_gid = (gid_offset + self.post.id_to_index(target)) * 2
#            post_pre_gid = pre_post_gid + 1
#            # Connect the pre cell voltage to the target var
##            print "Setting source_var on source cell {} to connect to target cell {} with gid {} on process {}".format(source, target, pre_post_gid, simulator.state.mpi_rank)
#            simulator.state.parallel_context.source_var(segment(0.5)._ref_v, pre_post_gid) #@UndefinedVariableFromImport                    
#            # Create the gap_junction and set its weight
#            gap_junction = h.Gap(0.5, sec=segment)
#            gap_junction.g = weight
#            # Store gap junction in a list so it doesn't get collected by the garbage 
#            # collector
#            segment._gap_junctions.append(gap_junction)
#            # Connect the gap junction with the source_var
##            print "Setting target_var on source cell {} to connect to target cell {} with gid {} on process {}".format(source, target, post_pre_gid, simulator.state.mpi_rank)
#            simulator.state.parallel_context.target_var(gap_junction._ref_vgap, post_pre_gid) #@UndefinedVariableFromImport              
#
#    def _convergent_connect(self, sources, target, weights, delays):
#        raise NotImplementedError


class Network(ninemlp.common.Network):

    def __init__(self, filename, build_mode=DEFAULT_BUILD_MODE, timestep=None, min_delay=None,
                                 max_delay=None, temperature=None, silent_build=False, flags=[]):
        self._pyNN_module = pyNN.neuron
        self._ncml_module = ncml
        self._Population_class = Population
        self._Projection_class = Projection
        self._GapJunctionProjection_class = GapJunctionProjection
        self.get_min_delay = get_min_delay # Sets the 'get_min_delay' function for use in the network init
        #Call the base function initialisation function.
        ninemlp.common.Network.__init__(self, filename, build_mode=build_mode, timestep=timestep,
                                        min_delay=min_delay, max_delay=max_delay,
                                    temperature=temperature, silent_build=silent_build, flags=flags)

    def _convert_units(self, value_str, units=None):
        if ' ' in value_str:
            if units:
                raise Exception("Units defined in both argument ('{}') and value string ('{}')"
                                .format(units, value_str))
            (value, units) = value_str.split()
        else:
            value = value_str
            units = None
        try:
            value = float(value)
        except:
            raise Exception("Incorrectly formatted value string '{}', should be a number optionally"
                            " followed by a space and units (eg. '1.5 Hz')".format(value_str))
        if not units:
            return value
        elif units == "Hz":
            return value
        elif units == "um":
            return value
        elif units == "ms":
            return value
        elif units == "us":
            return value * 1e-3
        elif units == "us/um":
            return value * 1e-3
        elif units == 'uS':
            return value
        elif units == 'mS':
            return value * 1e+3
        elif units == 'nS':
            return value * 1e-3
        elif units == 'pS':
            return value * 1e-6
        elif units == 'MOhm':
            return value
        elif units == 'Ohm/cm':
            return value
        elif units == 'S/cm2':
            return value
        else:
            raise Exception("Unrecognised units '%s'" % units)


    def _set_simulation_params(self, **params):
        """
        Sets the simulation parameters either from the passed parameters or from the networkML
        description
        
        @param params[**kwargs]: Parameters that are either passed to the pyNN setup method or set \
                                 explicitly
        """
        p = self._get_simulation_params(**params)
        setup(p['timestep'], p['min_delay'], p['max_delay'])
        neuron.h.celsius = p['temperature']


    def _get_target_str(self, synapse, segment=None):
        if not segment:
            segment = "source_section"
        return seg_varname(segment) + "." + synapse

    def _finalise_construction(self):
        includes_electrical = False
        for proj in self.all_projections():
            if isinstance(proj, GapJunctionProjection):
                includes_electrical = True
        if includes_electrical:
            print "Setting up transfer on MPI process {}".format(simulator.state.mpi_rank)
            simulator.state.parallel_context.setup_transfer() #@UndefinedVariableFromImport

if __name__ == "__main__":

    net = Network('/home/tclose/Projects/Cerebellar/xml/cerebellum/test.xml')

    print 'done'

