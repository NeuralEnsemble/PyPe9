from __future__ import division
import unittest
from nineml.user import (
    Projection, Network, DynamicsProperties,
    Population, ComponentArray, EventConnectionGroup,
    MultiDynamics)
from nineml.user.projection import Connectivity
from nineml.abstraction import (
    Parameter, Dynamics, Regime, On, OutputEvent, StateVariable,
    StateAssignment, Constant, Alias)
from nineml.abstraction.ports import (
    AnalogSendPort, AnalogReceivePort, AnalogReducePort, EventSendPort,
    EventReceivePort)
from nineml import units as un
from nineml.units import ms
from pype9.base.network import Network as BaseNetwork
import ninemlcatalog


class TestNetwork(unittest.TestCase):

    delay = 1 * un.ms

    def setUp(self):
        self.all_to_all = ninemlcatalog.load('/connectionrule/AllToAll',
                                             'AllToAll')

    def test_component_arrays_and_connection_groups(self):

        # =====================================================================
        # Dynamics components
        # =====================================================================

        cell1_cls = Dynamics(
            name='Cell',
            state_variables=[
                StateVariable('SV1', dimension=un.voltage)],
            regimes=[
                Regime(
                    'dSV1/dt = -SV1 / P1 + i_ext / P2',
                    transitions=[On('SV1 > P3', do=[OutputEvent('spike')])],
                    name='R1')],
            analog_ports=[AnalogReducePort('i_ext', dimension=un.current,
                                           operator='+'),
                          EventSendPort('spike')],
            parameters=[Parameter('P1', dimension=un.time),
                        Parameter('P2', dimension=un.capacitance),
                        Parameter('P3', dimension=un.voltage)])

        cell2_cls = Dynamics(
            name='Cell',
            state_variables=[
                StateVariable('SV1', dimension=un.voltage)],
            regimes=[
                Regime(
                    'dSV1/dt = -SV1 ^ 2 / P1 + i_ext / P2',
                    transitions=[On('SV1 > P3', do=[OutputEvent('spike')]),
                                 On('SV1 > P4',
                                    do=[OutputEvent('double_spike')])],
                    name='R1')],
            analog_ports=[AnalogReducePort('i_ext', dimension=un.current,
                                           operator='+')],
            parameters=[Parameter('P1', dimension=un.time * un.voltage),
                        Parameter('P2', dimension=un.capacitance),
                        Parameter('P3', dimension=un.voltage),
                        Parameter('P4', dimension=un.voltage)])

        exc_cls = Dynamics(
            name="Exc",
            aliases=["i := SV1"],
            regimes=[
                Regime(
                    name="default",
                    time_derivatives=[
                        "dSV1/dt = SV1/tau"],
                    transitions=[
                        On('spike', do=["SV1 = SV1 + weight"]),
                        On('double_spike', do=['SV1 = SV1 + 2 * weight'])])],
            state_variables=[
                StateVariable('SV1', dimension=un.current),
            ],
            analog_ports=[AnalogSendPort("i", dimension=un.current),
                          AnalogReceivePort("weight", dimension=un.current)],
            parameters=[Parameter('tau', dimension=un.time)])

        inh_cls = Dynamics(
            name="Inh",
            aliases=["i := SV1"],
            regimes=[
                Regime(
                    name="default",
                    time_derivatives=[
                        "dSV1/dt = SV1/tau"],
                    transitions=On('spike', do=["SV1 = SV1 - weight"]))],
            state_variables=[
                StateVariable('SV1', dimension=un.current),
            ],
            analog_ports=[AnalogSendPort("i", dimension=un.current),
                          AnalogReceivePort("weight", dimension=un.current)],
            parameters=[Parameter('tau', dimension=un.time)])

        static_cls = Dynamics(
            name="Static",
            aliases=["fixed_weight := weight"],
            regimes=[
                Regime(name="default")],
            analog_ports=[AnalogSendPort("fixed_weight",
                                         dimension=un.current)],
            parameters=[Parameter('weight', dimension=un.current)])

        stdp_cls = Dynamics(
            name="PartialStdpGuetig",
            parameters=[
                Parameter(name='tauLTP', dimension=un.time),
                Parameter(name='aLTD', dimension=un.dimensionless),
                Parameter(name='wmax', dimension=un.dimensionless),
                Parameter(name='muLTP', dimension=un.dimensionless),
                Parameter(name='tauLTD', dimension=un.time),
                Parameter(name='aLTP', dimension=un.dimensionless)],
            analog_ports=[
                AnalogSendPort(dimension=un.dimensionless, name="wsyn"),
                AnalogSendPort(dimension=un.current, name="wsyn_current")],
            event_ports=[
                EventReceivePort(name="incoming_spike")],
            state_variables=[
                StateVariable(name='tlast_post', dimension=un.time),
                StateVariable(name='tlast_pre', dimension=un.time),
                StateVariable(name='deltaw', dimension=un.dimensionless),
                StateVariable(name='interval', dimension=un.time),
                StateVariable(name='M', dimension=un.dimensionless),
                StateVariable(name='P', dimension=un.dimensionless),
                StateVariable(name='wsyn', dimension=un.dimensionless)],
            constants=[Constant('ONE_NA', 1.0, un.nA)],
            regimes=[
                Regime(
                    name="sole",
                    transitions=On(
                        'incoming_spike',
                        to='sole',
                        do=[
                            StateAssignment('tlast_post', 't'),
                            StateAssignment('tlast_pre', 'tlast_pre'),
                            StateAssignment(
                                'deltaw',
                                'P*pow(wmax - wsyn, muLTP) * '
                                'exp(-interval/tauLTP) + deltaw'),
                            StateAssignment('interval', 't - tlast_pre'),
                            StateAssignment(
                                'M', 'M*exp((-t + tlast_post)/tauLTD) - aLTD'),
                            StateAssignment(
                                'P', 'P*exp((-t + tlast_pre)/tauLTP) + aLTP'),
                            StateAssignment('wsyn', 'deltaw + wsyn')]))],
            aliases=[Alias('wsyn_current', 'wsyn * ONE_NA')])

        exc = DynamicsProperties(
            name="ExcProps",
            definition=exc_cls, properties={'tau': 1 * ms})

        inh = DynamicsProperties(
            name="ExcProps",
            definition=inh_cls, properties={'tau': 1 * ms})

        static = DynamicsProperties(name="StaticProps",
                                    definition=static_cls,
                                    properties={'weight': 1 * un.nA})

        stdp = DynamicsProperties(name="StdpProps", definition=stdp_cls,
                                  properties={'tauLTP': 10 * un.ms,
                                              'aLTD': 1,
                                              'wmax': 2,
                                              'muLTP': 3,
                                              'tauLTD': 20 * un.ms,
                                              'aLTP': 4})

        # =====================================================================
        # Populations and Projections
        # =====================================================================

        pop1 = Population(
            name="Pop1",
            size=10,
            cell=DynamicsProperties(
                name="Pop1Props",
                definition=cell1_cls,
                properties={'P1': 10 * un.ms,
                            'P2': 100 * un.uF,
                            'P3': -50 * un.mV}))

        pop2 = Population(
            name="Pop2",
            size=15,
            cell=DynamicsProperties(
                name="Pop2Props",
                definition=cell2_cls,
                properties={'P1': 20 * un.ms * un.mV,
                            'P2': 50 * un.uF,
                            'P3': -40 * un.mV,
                            'P4': -20 * un.mV}))

        pop3 = Population(
            name="Pop3",
            size=20,
            cell=DynamicsProperties(
                name="Pop3Props",
                definition=cell1_cls,
                properties={'P1': 30 * un.ms,
                            'P2': 50 * un.pF,
                            'P3': -20 * un.mV}))

        proj1 = Projection(
            name="Proj1",
            pre=pop1, post=pop2, response=inh, plasticity=static,
            connectivity=self.all_to_all,
            port_connections=[
                ('pre', 'spike', 'response', 'spike'),
                ('response', 'i', 'post', 'i_ext'),
                ('plasticity', 'fixed_weight', 'response', 'weight')],
            delay=self.delay)

        proj2 = Projection(
            name="Proj2",
            pre=pop2, post=pop1, response=exc, plasticity=static,
            connectivity=self.all_to_all,
            port_connections=[
                ('pre', 'spike', 'response', 'spike'),
                ('pre', 'double_spike', 'response', 'double_spike'),
                ('response', 'i', 'post', 'i_ext'),
                ('plasticity', 'fixed_weight', 'response', 'weight')],
            delay=self.delay)

        proj3 = Projection(
            name="Proj3",
            pre=pop3, post=pop2, response=exc, plasticity=stdp,
            connectivity=self.all_to_all,
            port_connections=[
                ('pre', 'spike', 'response', 'spike'),
                ('response', 'i', 'post', 'i_ext'),
                ('plasticity', 'wsyn_current', 'response', 'weight'),
                ('pre', 'spike', 'plasticity', 'incoming_spike')],
            delay=self.delay)

        proj4 = Projection(
            name="Proj4",
            pre=pop3, post=pop1, response=exc, plasticity=static,
            connectivity=self.all_to_all,
            port_connections=[
                ('pre', 'spike', 'response', 'spike'),
                ('response', 'i', 'post', 'i_ext'),
                ('plasticity', 'fixed_weight', 'response', 'weight')],
            delay=self.delay)

        # =====================================================================
        # Construct the Network
        # =====================================================================

        network = Network(
            name="Net",
            populations=(pop1, pop2, pop3),
            projections=(proj1, proj2, proj3, proj4))

        # =====================================================================
        # Create expected dynamics arrays
        # =====================================================================

        dyn_array1 = ComponentArray(
            "Pop1", pop1.size,
            MultiDynamics(
                "Pop1",
                sub_components={'cell': cell1_cls,
                                'Proj2_psr': exc_cls,
                                'Proj4_psr': exc_cls,
                                'Proj2_pls': static_cls,
                                'Proj4_pls': static_cls},
                port_connections=[
                    ('Proj2_psr', 'i', 'cell', 'i_ext'),
                    ('Proj2_pls', 'fixed_weight', 'Proj2_psr', 'weight'),
                    ('Proj4_psr', 'i', 'cell', 'i_ext'),
                    ('Proj4_pls', 'fixed_weight', 'Proj4_psr', 'weight')],
                port_exposures=[
                    ('cell', 'spike'),
                    ('Proj2_psr', 'double_spike'),
                    ('Proj2_psr', 'spike'),
                    ('Proj4_psr', 'spike')]))

        dyn_array2 = ComponentArray(
            "Pop2", pop2.size,
            MultiDynamics(
                "Pop2",
                sub_components={'cell': cell2_cls,
                                'Proj1_psr': inh_cls,
                                'Proj3_psr': exc_cls,
                                'Proj1_pls': static_cls,
                                'Proj3_pls': stdp_cls},
                port_connections=[
                    ('Proj1_psr', 'i', 'cell', 'i_ext'),
                    ('Proj1_pls', 'fixed_weight', 'Proj1_psr', 'weight'),
                    ('Proj3_psr', 'i', 'cell', 'i_ext'),
                    ('Proj3_pls', 'wsyn_current', 'Proj3_psr', 'weight')],
                port_exposures=[
                    ('cell', 'spike'),
                    ('cell', 'double_spike'),
                    ('Proj1_psr', 'spike'),
                    ('Proj3_psr', 'spike'),
                    ('Proj3_pls', 'incoming_spike')]))

        dyn_array3 = ComponentArray(
            "Pop3", pop3.size, MultiDynamics(
                'Pop3',
                sub_components={'cell': cell1_cls},
                port_exposures=[('cell', 'spike')]))

        conn_group1 = EventConnectionGroup(
            'Proj1__pre_spike__response_spike___connection_group', 'Pop1',
            'Pop2', 'spike__cell', 'spike__Proj1_psr',
            Connectivity(self.all_to_all, pop1, pop2), self.delay)

        conn_group2 = EventConnectionGroup(
            'Proj2__pre_spike__response_spike___connection_group', 'Pop2',
            'Pop1', 'spike__cell', 'spike__Proj2_psr',
            Connectivity(self.all_to_all, pop2, pop1), self.delay)

        conn_group3 = EventConnectionGroup(
            'Proj2__pre_double_spike__response_double_spike'
            '___connection_group',
            'Pop2', 'Pop1', 'double_spike__cell',
            'double_spike__Proj2_psr',
            Connectivity(self.all_to_all, pop2, pop1), self.delay)

        conn_group4 = EventConnectionGroup(
            'Proj3__pre_spike__response_spike___connection_group', 'Pop3',
            'Pop2', 'spike__cell', 'spike__Proj3_psr',
            Connectivity(self.all_to_all, pop3, pop2), self.delay)

        conn_group5 = EventConnectionGroup(
            'Proj3__pre_spike__plasticity_incoming_spike___connection_group',
            'Pop3', 'Pop2', 'spike__cell', 'incoming_spike__Proj3_pls',
            Connectivity(self.all_to_all, pop3, pop2), self.delay)

        conn_group6 = EventConnectionGroup(
            'Proj4__pre_spike__response_spike___connection_group', 'Pop3',
            'Pop1', 'spike__cell', 'spike__Proj4_psr',
            Connectivity(self.all_to_all, pop3, pop1), self.delay)

        # =====================================================================
        # Test equality between network automatically generated dynamics arrays
        # and manually generated expected one
        # =====================================================================
        (component_arrays,
         connection_groups) = BaseNetwork.nineml_comp_arrays_and_conn_groups(
            network)

        self.assertEqual(network.num_component_arrays, 3)
        self.assertEqual(
            component_arrays['Pop1'], dyn_array1,
            "Mismatch between generated and expected dynamics arrays:\n {}"
            .format(component_arrays['Pop1'].find_mismatch(dyn_array1)))
        self.assertEqual(
            component_arrays['Pop2'], dyn_array2,
            "Mismatch between generated and expected dynamics arrays:\n {}"
            .format(component_arrays['Pop2'].find_mismatch(dyn_array2)))
        self.assertEqual(
            component_arrays['Pop3'], dyn_array3,
            "Mismatch between generated and expected dynamics arrays:\n {}"
            .format(component_arrays['Pop3'].find_mismatch(dyn_array3)))
        # =====================================================================
        # Test equality between network automatically generated connection
        # groups and manually generated expected ones
        # =====================================================================
        self.assertEqual(network.num_connection_groups, 6)
        self.assertEqual(
            connection_groups[
                'Proj1__pre_spike__response_spike___connection_group'],
            conn_group1,
            "Mismatch between generated and expected connection groups:\n {}"
            .format(
                connection_groups[
                    'Proj1__pre_spike__response_spike___connection_group']
                .find_mismatch(conn_group1)))
        self.assertEqual(
            connection_groups[
                'Proj2__pre_spike__response_spike___connection_group'],
            conn_group2,
            "Mismatch between generated and expected connection groups:\n {}"
            .format(
                connection_groups[
                    'Proj2__pre_spike__response_spike___connection_group']
                .find_mismatch(conn_group2)))
        self.assertEqual(
            connection_groups[
                'Proj2__pre_double_spike__response_double_spike'
                '___connection_group'],
            conn_group3,
            "Mismatch between generated and expected connection groups:\n {}"
            .format(
                connection_groups[
                    'Proj2__pre_double_spike__response_double_spike'
                    '___connection_group']
                .find_mismatch(conn_group3)))
        self.assertEqual(
            connection_groups[
                'Proj3__pre_spike__response_spike___connection_group'],
            conn_group4,
            "Mismatch between generated and expected connection groups:\n {}"
            .format(
                connection_groups[
                    'Proj3__pre_spike__response_spike___connection_group']
                .find_mismatch(conn_group4)))
        self.assertEqual(
            connection_groups[
                'Proj3__pre_spike__plasticity_incoming_spike'
                '___connection_group'],
            conn_group5,
            "Mismatch between generated and expected connection groups:\n {}"
            .format(
                connection_groups[
                    'Proj3__pre_spike__plasticity_incoming_spike'
                    '___connection_group']
                .find_mismatch(conn_group5)))
        self.assertEqual(
            connection_groups[
                'Proj4__pre_spike__response_spike___connection_group'],
            conn_group6,
            "Mismatch between generated and expected connection groups:\n {}"
            .format(
                connection_groups[
                    'Proj4__pre_spike__response_spike___connection_group']
                .find_mismatch(conn_group6)))