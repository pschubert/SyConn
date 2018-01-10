from PythonQt import QtGui, Qt, QtCore
import KnossosModule
import sys
import requests
import json
sys.dont_write_bytecode = True

class SyConnGateInteraction(object):
    """
    Query the SyConn backend server.
    """
    def __init__(self, server):
        self.server = server
        self.session = requests.Session()
        self.ssv_from_sv_cache = dict()
        self.svs_from_ssv = dict()

    def get_ssv_mesh(self, ssv_id):
        """
        Returns a mesh for a given ssv_id.
        Parameters
        ----------
        ssv_id

        Returns
        -------

        """
        r = self.session.get(self.server + '/ssv_mesh/{0}'.format(ssv_id))
        return json.loads(r.content)

    def get_ssv_obj_mesh(self, ssv_id, obj_type):
        """
        Returns a mesh for a given ssv_id and a specified obj_type.
        obj_type can be sj, vc, mi ATM.
        Parameters
        ----------
        ssv_id
        obj_type

        Returns
        -------

        """
        r = self.session.get(self.server + '/ssv_obj_mesh/{0}/{1}'.format(ssv_id,
                                                                          obj_type))
        return json.loads(r.content)

    def get_list_of_all_ssv_ids(self):
        """
        Returns a list of all ssvs in the dataset
        Returns
        -------

        """
        r = self.session.get(self.server + '/ssv_list')
        return json.loads(r.content)

    def get_svs_of_ssv(self, ssv_id):
        """
        Returns a list of all svs of a given ssv.
        Parameters
        ----------
        ssv_id

        Returns
        -------

        """
        if not self.svs_from_ssv.has_key(ssv_id):
            r = self.session.get(self.server + '/svs_of_ssv/{0}'.format(ssv_id))
            self.svs_from_ssv[ssv_id] = json.loads(r.content)
        return self.svs_from_ssv[ssv_id]

    def get_ssv_of_sv(self, sv_id):
        """
        Gets the ssv for a given sv.
        Parameters
        ----------
        sv_id

        Returns
        -------

        """
        if not self.ssv_from_sv_cache.has_key(sv_id):
            r = self.session.get(self.server + '/ssv_of_sv/{0}'.format(sv_id))
            self.ssv_from_sv_cache[sv_id] = json.loads(r.content)
        return self.ssv_from_sv_cache[sv_id]

    def get_all_syn_metda_data(self):
        """

        Returns
        -------

        """
        r = self.session.get(self.server + '/all_syn_meta')
        return json.loads(r.content)

class main_class(QtGui.QDialog):
    """
    KNOSSOS plugin class for the SyConn KNOSSOS viewer.
    """
    def __init__(self, parent=KnossosModule.knossos_global_mainwindow):
        #Qt.QApplication.processEvents()
        super(main_class, self).__init__(parent, Qt.Qt.WA_DeleteOnClose)
        try:
            exec(KnossosModule.scripting.getInstanceInContainerStr(__name__)\
                 + " = self")
        except KeyError:
            # Allow running from __main__ context
            pass
        #self.start_logging()

        self.ssv_selected1 = 0
        self.obj_tree_ids = set()
        self.obj_id_offs = 1000000000

        self.init_syconn()
        self.build_gui()

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.exploration_mode_callback_check)
        self.timer.start(1000)


    def init_syconn(self):
        # move to config file
        syconn_gate_server = 'http://localhost:10001'
        self.syconn_gate = SyConnGateInteraction(syconn_gate_server)

        return

    def populate_ssv_list(self):
        all_ssv_ids = self.syconn_gate.get_list_of_all_ssv_ids()['ssvs']

        #print('list of all here')
        #print(len(all_ssv_ids))
        for ssv_id in all_ssv_ids:
            #print(ssv_id)
            item = QtGui.QStandardItem(str(int(ssv_id)))
            self.ssv_item_model.appendRow(item)

        self.ssv_selector.setModel(self.ssv_item_model)
        return

    def populate_syn_list(self):
        all_syns = self.syconn_gate.get_all_syn_metda_data()

        #print('list of all here')
        #print(len(all_ssv_ids))
        for syn in zip(all_syns['ssv_partner_0'], all_syns['ssv_partner_1']):
            item = QtGui.QStandardItem(str(syn))
            self.syn_item_model.appendRow(item)

        self.syn_selector.setModel(self.syn_item_model)
        return


    def on_ssv_selector_changed(self, index):
        self.ssv_selected1 = int(self.ssv_selector.model().itemData(index)[0])
        #current, previous
        #print('selected: ' + str(self.ssv_selector.model().itemData(index)[0]))
        #ssv = self.get_ssv(self.ssv_selected1)
        #self.ssv_to_knossos(ssv)

        return

    def on_ssv_selector_changed(self, index):
        self.ssv_selected1 = int(self.ssv_selector.model().itemData(index)[0])
        #current, previous
        #print('selected: ' + str(self.ssv_selector.model().itemData(index)[0]))
        #ssv = self.get_ssv(self.ssv_selected1)
        #self.ssv_to_knossos(ssv)

        return

    def build_gui(self):
        self.setWindowFlags(Qt.Qt.Window)
        layout = QtGui.QGridLayout()
        layout.setSpacing(10)

        # Window layout
        #layout = QtGui.QVBoxLayout()
        self.setLayout(layout)

        self.show_button = QtGui.QPushButton('Show neurite')
        self.clear_knossos_view_button = QtGui.QPushButton('Clear view')

        self.ssv_selector = QtGui.QListView()
        self.ssv_selector.setUniformItemSizes(True) # better performance
        self.ssv_item_model = QtGui.QStandardItemModel(self.ssv_selector)

        self.syn_selector = QtGui.QListView()
        self.syn_selector.setUniformItemSizes(True) # better performance
        self.syn_item_model = QtGui.QStandardItemModel(self.syn_selector)

        self.direct_ssv_id_input = QtGui.QLineEdit()
        self.direct_ssv_id_input.setValidator(QtGui.QIntValidator())
        self.direct_ssv_id_input.setMaxLength(16)

        self.exploration_mode_chk_box = QtGui.QCheckBox('Exploration mode')
        self.exploration_mode_chk_box.setChecked(False)
        #self.ssv_selection_model =
        # QtGui.QItemSelectionModel(self.ssv_select_model)

        #self.selectionModel =
        # self.ssv_selector.selectionModel(self.ssv_selector)
        #self.ssv_selector.setSelectionModel(self.ssv_selection_model)
        #print('selection model: ' + str(self.ssv_selector.selectionModel()))

        self.ssv_selector.clicked.connect(self.on_ssv_selector_changed)
        self.syn_selector.clicked.connect(self.on_ssv_selector_changed)

        self.populate_ssv_list()

        self.populate_syn_list()
        print('Connected to SyConnFS backend')

        layout.addWidget(self.direct_ssv_id_input, 1, 0, 1, 2)
        layout.addWidget(self.ssv_selector, 2, 0, 1, 1)
        layout.addWidget(self.syn_selector, 2, 1, 1, 1)
        layout.addWidget(self.show_button, 3, 0, 1, 1)
        layout.addWidget(self.clear_knossos_view_button, 3, 1, 1, 1)
        layout.addWidget(self.exploration_mode_chk_box, 4, 0, 1, 2)

        #self.ssv_select_model.itemChanged.connect(self.on_ssv_selector_changed)
        #self.selectionModel.selectionChanged.connect(self.on_ssv_selector_changed)

        self.show_button.clicked.connect(self.show_button_clicked)
        self.clear_knossos_view_button.clicked.connect(self.clear_knossos_view_button_clicked)
        self.exploration_mode_chk_box.stateChanged.connect(self.exploration_mode_changed)

        self.setGeometry(300, 300, 450, 300)
        self.setWindowTitle('SyConn Viewer v1')
        self.show()
        #self.merge_button = QtGui.QPushButton('Merge')
        #self.split_button = QtGui.QPushButton('Split')


#        QList < quint64 > subobjectIdsOfObject(const
 #       quint64
  #      objId);

   #     QList < quint64 > objects();
    #    QList < quint64 > selectedObjects();


        #self.bad_button = QtGui.QPushButton('Bad SV')
        #self.graph_split_button = QtGui.QPushButton('Graph split')
        #self.add_selected_sv_button = QtGui.QPushButton('Add selected SV')
        #self.mode_combo = QtGui.QComboBox()
        #self.stop_button = QtGui.QPushButton('Stop')
        #self.undo_button = QtGui.QPushButton('Undo')
        #self.redo_button = QtGui.QPushButton('Redo')

        #self.skip_task_line_edit = QtGui.QLineEdit('Skip reason')
        #self.server_line_edit = QtGui.QLineEdit()

        #self.password_line_edit = QtGui.QLineEdit()
        #  set echo mode to QLineEdit::PasswordEchoOnEdit

        #self.gui_auto_agglo_line_edit = QtGui.QLineEdit()
        #self.gui_auto_agglo_line_edit.setText('0')

    def exploration_mode_changed(self):

        if self.exploration_mode_chk_box.isChecked():
            pass
            # enable selection polling timer
        else:
            pass
            # disable selection polling timer

    def exploration_mode_callback_check(self):
        if self.exploration_mode_chk_box.isChecked():

            sel_seg_objs = KnossosModule.segmentation.selectedObjects()
            sel_sv_ids = []
            for sel_seg_obj in sel_seg_objs:
                sel_sv_ids.append(KnossosModule.segmentation.subobjectIdsOfObject(sel_seg_obj)[0])

            # get selected ssv ids
            ssv_ids_selected = [self.syconn_gate.get_ssv_of_sv(sv_id)['ssv'] for sv_id in sel_sv_ids]

            # id_changer returns -1 for a supervoxel that is unconnected, add support for single svs
            ssv_ids_selected = [ssv_id for ssv_id in ssv_ids_selected if ssv_id != -1]

            #print('ssv_ids_selected {0}'.format(ssv_ids_selected))

            trees = KnossosModule.skeleton.trees()
            ids_in_k = set([tree.tree_id() for tree in trees])

            #print('self.obj_tree_ids {0}'.format(self.obj_tree_ids))
            #print('ids_in_k 1 {0}'.format(ids_in_k))

            ids_in_k = ids_in_k - self.obj_tree_ids
            #print('ids_in_k 2 {0}'.format(ids_in_k))

            # compare with the selected segmentation objects
            ids_selected = set(ssv_ids_selected)

            # add missing ones to knossos, delete if not needed anymore
            ids_to_add = ids_selected - ids_in_k
            ids_to_del = ids_in_k - ids_selected

            # remove segmentation objects that are not needed anymore
            all_objects = KnossosModule.segmentation.objects()

            objs_to_del = set(all_objects) - set(ids_selected)

            [KnossosModule.segmentation.removeObject(obj) for obj in objs_to_del]

            #print('ids to del {0} ids to add {1}'.format(ids_to_del, ids_to_add))

            print('ids_selected {0}'.format(ids_selected))
            self.ids_selected = ids_selected

            [KnossosModule.skeleton.delete_tree(sv_id) for sv_id in ids_to_del]
            [self.ssv_to_knossos(ssv_id) for ssv_id in ids_to_add]

            if len(ids_in_k) != 1 or len(ids_to_del) > 0:
                [KnossosModule.skeleton.delete_tree(sv_id) for sv_id in
                 self.obj_tree_ids]
                self.obj_tree_ids = set()

        return


    def show_button_clicked(self):
        try:
            self.ssv_selected1 = int(self.direct_ssv_id_input.text)
        except:
            pass

        if self.ssv_selected1:
            self.ssv_to_knossos(self.ssv_selected1)

        return

    def clear_knossos_view_button_clicked(self):

        # delete all existing objects in mergelist
        all_objects = KnossosModule.segmentation.objects()
        [KnossosModule.segmentation.removeObject(obj) for obj in all_objects]

        # iterate over all trees in knossos and delete
        trees = KnossosModule.skeleton.trees()
        ids_in_k = set([tree.tree_id() for tree in trees])
        [KnossosModule.skeleton.delete_tree(sv_id) for sv_id in ids_in_k]

        return

    def ssv_to_knossos(self, ssv_id):

        #self.clear_knossos_view_button_clicked()

        # to mergelist
        sv_ids = self.syconn_gate.get_svs_of_ssv(ssv_id)['svs']
        sv_ids = map(int, sv_ids)

        KnossosModule.segmentation.createObject(ssv_id, sv_ids[0], (1,1,1))
        #KnossosModule.segmentation.selectObject(ssv.id)
        # query object should be red
        #KnossosModule.segmentation.changeColor(ssv_id, QtGui.QColor(255, 0, 0, 255))

        # one could cache this, not necessary to rebuild at every step
        for sv_id in sv_ids:
            try:
                KnossosModule.segmentation.addSubobject(ssv_id, sv_id)
            except:
                pass

        KnossosModule.segmentation.selectObject(ssv_id)

        KnossosModule.segmentation.setRenderOnlySelectedObjs(True)

        print('self.ids_selected {0}'.format(self.ids_selected))

        if len(self.ids_selected) == 1:

            # create a 'fake' knossos tree for each obj mesh category;
            # this is very hacky since it can generate nasty ID collisions.
            mi_id = self.obj_id_offs + ssv_id + 1
            sj_id = self.obj_id_offs + ssv_id + 2
            vc_id = self.obj_id_offs + ssv_id + 3

            self.obj_tree_ids.add(mi_id)
            self.obj_tree_ids.add(sj_id)
            self.obj_tree_ids.add(vc_id)

            mi_mesh = self.syconn_gate.get_ssv_obj_mesh(ssv_id, 'mi')
            KnossosModule.skeleton.add_tree_mesh(mi_id, mi_mesh['indices'], [],
                                                 mi_mesh['vertices'],
                                                 [],
                                                 KnossosModule.GL_TRIANGLES,
                                                 False)
            KnossosModule.skeleton.set_tree_color(mi_id,
                                                  QtGui.QColor(0, 0, 255, 255))

            sj_mesh = self.syconn_gate.get_ssv_obj_mesh(ssv_id, 'sj')
            KnossosModule.skeleton.add_tree_mesh(sj_id, sj_mesh['indices'], [],
                                                 sj_mesh['vertices'],
                                                 [],
                                                 KnossosModule.GL_TRIANGLES,
                                                 False)
            KnossosModule.skeleton.set_tree_color(sj_id,
                                                  QtGui.QColor(0, 0, 0, 255))

            vc_mesh = self.syconn_gate.get_ssv_obj_mesh(ssv_id, 'vc')

            KnossosModule.skeleton.add_tree_mesh(vc_id, vc_mesh['indices'], [],
                                                 vc_mesh['vertices'],
                                                 [],
                                                 KnossosModule.GL_TRIANGLES,
                                                 False)
            KnossosModule.skeleton.set_tree_color(vc_id,
                                                  QtGui.QColor(0, 255, 0, 255))

            mesh = self.syconn_gate.get_ssv_mesh(ssv_id)
            KnossosModule.skeleton.add_tree_mesh(ssv_id, mesh['indices'], [],
                                                 mesh['vertices'],
                                                 [],
                                                 KnossosModule.GL_TRIANGLES,
                                                 False)
            KnossosModule.skeleton.set_tree_color(ssv_id,
                                                  QtGui.QColor(255, 0, 0, 128))
        else:
            mesh = self.syconn_gate.get_ssv_mesh(ssv_id)
            KnossosModule.skeleton.add_tree_mesh(ssv_id, mesh['indices'], [],
                                                 mesh['vertices'],
                                                 [],
                                                 KnossosModule.GL_TRIANGLES,
                                                 False)


        return


if __name__=='__main__':
    A = main_class()