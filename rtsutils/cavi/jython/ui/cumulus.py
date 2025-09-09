"""Java Swing UI for Cumulus API downloading grids
"""

import os
import json
from copy import deepcopy
from datetime import datetime
from java.lang import Short, Runnable
from java.awt import EventQueue, Font, Point, Cursor
from javax.swing import (
    BorderFactory,
    GroupLayout,
    ImageIcon,
    JButton,
    JFrame,
    JLabel,
    JList,
    JOptionPane,
    JScrollPane,
    JTextField,
    LayoutStyle,
    ListSelectionModel,
    SwingConstants,
)
from rtsutils import go
from rtsutils.cavi.jython import jutil
from rtsutils.utils.config import DictConfig
from rtsutils.utils import CLOUD_ICON, product_index, product_refactor, watershed_index, watershed_refactor

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class CumulusConnectionError(Exception):
    pass


class Cumulus():
    cumulus_configs = {}
    go_config = {}
    products_meta = None
    watersheds_meta = None
    publish = None

    def __init__(self, publish=None):
        """Initializes the Cumulus download manager class.

        Parameters
        ----------
        publish : callable, optional
            A callback function that takes a single string (for log messages) or a
            single integer (for progress bar updates) as an argument.  Passes real-time
            updates to an external GUI.  By default, None.
        """
        Cumulus.publish = publish
        Cumulus.report("Cumulus data request has been initialized.")

    @classmethod
    def report(cls, msg):
        """Publishes or prints a timestamped status update.

        Parameters
        ----------
        msg : str
            The string to be published or printed.
        """
        now_dt = datetime.strftime(datetime.now(), '%Y/%m/%d %H:%M:%S')
        dt_msg = '{} {}'.format(now_dt, msg)
        if cls.publish:
            cls.publish(dt_msg)
        else:
            print(dt_msg)

    @classmethod
    def invoke(cls):
        """The invoke classmethod 'runs' the runnable cumulus class
        """
        EventQueue.invokeLater(cls.Cumulus_Runnable())

    @classmethod
    def execute(cls, use_cache=True):
        """executing the Go binding as a subprocess"""
        configurations = DictConfig(cls.cumulus_configs).read()

        cls.go_config.update({
            "StdOut": "true",
            "Subcommand": "grid",
            "Endpoint": "deprecated/anonymous_downloads",
            "ID": configurations["watershed_id"],
            "Products": configurations["product_ids"],
        })

        product_list = ", ".join([cls.get_product_by_id(product_id)["name"]
                                 for product_id in configurations["product_ids"]])
        cls.report("Requested products: {}".format(product_list))
        cls.report("Requested time window: {} - {}".format(cls.go_config["After"], cls.go_config["Before"]))

        if use_cache:
            cls.report("Updating time window based on cached/existing data...")
            cls.adjust_dates_by_cache()
            after = datetime.strptime(cls.go_config["After"], ISO_FORMAT)
            before = datetime.strptime(cls.go_config["Before"], ISO_FORMAT)
            if before <= after:
                cls.report("All requested observed data has been previously downloaded.")
                cls.report("Removing observed products...")
                cls.remove_observed_products()
                if not cls.go_config["Products"]:
                    cls.report("No product downloads required.  Aborting...")
                    return
            else:
                totalTime = before - after
                timeout = int(totalTime.days * 20)
                if timeout < 300:
                    timeout = 300
                cls.report("Updated time window: {} - {}".format(cls.go_config["After"], cls.go_config["Before"]))
                cls.go_config.update({"Timeout": timeout})
                cls.report("Updated timeout value: {} seconds".format(timeout))

        cls.report("---BEGIN CUMULUS DOWNLOAD SUBROUTINE---")
        stdout, stderr = go.get(
            cls.go_config,
            out_err=True,
            is_shell=False,
            realtime=True,
            publish=cls.publish
        )
        cls.report("---CUMULUS DOWNLOAD SUBROUTINE COMPLETE---")
        if "error" in stderr:
            if cls.publish is None:
                JOptionPane.showMessageDialog(
                    None,
                    stderr.split("::")[-1],
                    "Program Error",
                    JOptionPane.ERROR_MESSAGE,
                )
            else:
                err = stderr.split("::")[-1]
                cls.report("Program Error: {}".format(err))
                raise Exception(err)
        else:
            _, file_path = stdout.split("::")
            jutil.copy_dss(file_path, configurations["dss"])

            cls.report("Cumulus download completed successfully.")
            if cls.publish is None:
                JOptionPane.showMessageDialog(
                    None,
                    "Program Done",
                    "Program Done",
                    JOptionPane.INFORMATION_MESSAGE,
                )

    @classmethod
    def cumulus_configuration(cls, cfg):
        """Set the cumulus configuration file"""
        cls.cumulus_configs = cfg

    @classmethod
    def go_configuration(cls, dict_):
        """update Go parameters

        Parameters
        ----------
        dict_ : dict
            Go parameters to update class defined configurations
        """
        cls.go_config = dict_

    @classmethod
    def get_metadata(cls):
        """Retrieves Cumulus product and watershed metadata.

        If metadata has not been previously downloaded, executes a go
        subroutine to download the metadata.  Original go configuration
        is maintained after function runs.

        Returns
        -------
        products_meta : list[dict]
            Cumulus products metadata

        watersheds_meta : list[dict]
            Cumulus watersheds metadata
        """
        if all([cls.products_meta, cls.watersheds_meta]):
            return cls.products_meta, cls.watersheds_meta

        cls.report("Retrieving Cumulus product and watershed metadata...")
        orig_go_config = deepcopy(cls.go_config)

        try:
            cls.go_config["StdOut"] = "true"
            cls.go_config["Subcommand"] = "get"

            cls.go_config["Endpoint"] = "products"
            ps_out, stderr = go.get(cls.go_config, out_err=True, is_shell=False)
            if "error" in stderr:
                raise CumulusConnectionError(stderr)
            cls.products_meta = json.loads(ps_out)

            cls.go_config["Endpoint"] = "watersheds"
            ws_out, stderr = go.get(cls.go_config, out_err=True, is_shell=False)
            if "error" in stderr:
                raise CumulusConnectionError(stderr)
            cls.watersheds_meta = json.loads(ws_out)

            cls.report("Metadata retrieved!")

            return cls.products_meta, cls.watersheds_meta

        finally:
            cls.go_config = orig_go_config

    @classmethod
    def get_product(cls, name):
        """Retrieve product metadata by name.

        Parameters
        ----------
        name : string
            The name of the product.

        Returns
        -------
        dict or None
            The metadata of the product if found, or None if not.
        """
        products, _ = cls.get_metadata()
        for product in products:
            if product["name"] == name:
                return product
        return None

    @classmethod
    def get_product_by_id(cls, product_id):
        """Retrieve product metadata by id.

        Parameters
        ----------
        product_id : string
            The id of the product.

        Returns
        -------
        dict or None
            The metadata of the product if found, or None if not.
        """
        products, _ = cls.get_metadata()
        for product in products:
            if product["id"] == product_id:
                return product
        return None

    @classmethod
    def get_watershed(cls, office, name):
        """Retrieve watershed metadata by office symbol and name.

        Parameters
        ----------
        office : string
            The 3-letter office symbol for the watershed.
        name : string
            The name of the watershed.

        Returns
        -------
        dict or None
            The metadata of the watershed if found, or None if not.
        """
        _, watersheds = cls.get_metadata()
        for watershed in watersheds:
            if watershed["office_symbol"] == office and watershed["name"] == name:
                return watershed
        return None

    @classmethod
    def get_watershed_by_id(cls, watershed_id):
        """Retrieve watershed metadata by id.

        Parameters
        ----------
        watershed_id : string
            The id of the watershed.

        Returns
        -------
        dict or None
            The metadata of the watershed if found, or None if not.
        """
        _, watersheds = cls.get_metadata()
        for watershed in watersheds:
            if watershed["id"] == watershed_id:
                return watershed
        return None

    @classmethod
    def adjust_dates_by_cache(cls):
        """Removes existing data range from go_config time window

        Checks for existing data in the DSS file set in the cumulus configuration.
        Searches based on the b-part of the watershed and the f-part of the
        -first observed- product as listed in product_ids.

        The After and Before values within go_config are adjusted to avoid
        downloading data that already exists within the DSS file.
        """
        config = DictConfig(cls.cumulus_configs).read()

        after = datetime.strptime(cls.go_config["After"], ISO_FORMAT)
        before = datetime.strptime(cls.go_config["Before"], ISO_FORMAT)

        dss_path = config["dss"]
        b_part = cls.get_watershed_by_id(config["watershed_id"])["name"]
        for product_id in config["product_ids"]:
            product = cls.get_product_by_id(product_id)
            if product["last_forecast_version"]:  # Skip forecasts
                continue
            f_part = product["dss_fpart"]
            data_start, data_end = jutil.get_existing_precip_data_range(dss_path, b_part, f_part)
            if data_start is None or data_end is None:
                break
            if data_end > after > data_start:
                after = data_end
            if data_end > before > data_start:
                before = data_start
            cls.go_config["After"] = after.strftime(ISO_FORMAT)
            cls.go_config["Before"] = before.strftime(ISO_FORMAT)

    @classmethod
    def remove_observed_products(cls):
        """Remove non-forecast products from go_config."""
        product_ids = cls.go_config["Products"]
        forecast_product_ids = []
        for product_id in product_ids:
            product = cls.get_product_by_id(product_id)
            if product["last_forecast_version"] is not None:
                forecast_product_ids.append(product_id)
        cls.go_config["Products"] = forecast_product_ids

    class Cumulus_Runnable(Runnable):
        """java.lang.Runnable class executes run when called"""

        def select(self, event):
            """initiate Java Swing JFileChooser

            Parameters
            ----------
            event : ActionEvent
                component-defined action
            """
            file_chooser = jutil.FileChooser()
            file_chooser.title = "Select Output DSS File"
            try:
                _dir = os.path.dirname(self.dsspath.getText())
                file_chooser.set_current_dir(_dir)
            except TypeError as ex:
                print(ex)

            file_chooser.show()
            if file_chooser.output_path:
                self.dsspath.setText(file_chooser.output_path)

        def execute(self, event):
            """set configurations to execute Go binding

            Parameters
            ----------
            event : ActionEvent
                component-defined action
            """

            if self.save_config():
                source = event.getSource()
                prev = source.getCursor()
                source.setCursor(Cursor.getPredefinedCursor(Cursor.WAIT_CURSOR))
                self.outer_class.execute()
                source.setCursor(prev)

        def save(self, event):
            """save the selected configurations to file

            Parameters
            ----------
            event : ActionEvent
                component-defined action
            """
            if self.save_config():
                source = event.getSource()
                source.setText("Configuration Saved")

        def save_config(self):
            """save the selected configurations to file
            """
            selected_watershed = self.watershed_list.getSelectedValue()
            selected_products = self.product_list.getSelectedValues()
            dssfile = self.dsspath.getText()

            if selected_products and selected_watershed and dssfile:
                watershed_id = self.api_watersheds[selected_watershed]["id"]
                watershed_slug = self.api_watersheds[selected_watershed]["slug"]
                product_ids = [self.api_products[p]["id"] for p in selected_products]

                # Get, set and save jutil.configurations
                self.configurations["watershed_id"] = watershed_id
                self.configurations["watershed_slug"] = watershed_slug
                self.configurations["product_ids"] = product_ids
                self.configurations["dss"] = dssfile
                DictConfig(self.outer_class.cumulus_configs).write(self.configurations)
            else:
                JOptionPane.showMessageDialog(
                    None,
                    "Missing configuration inputs",
                    "Configuration Inputs",
                    JOptionPane.INFORMATION_MESSAGE,
                )
                return False
            return True

        def close(self, event):
            """Close the dialog

            Parameters
            ----------
            event : ActionEvent
                component-defined action
            """
            self.dispose()

        def create_jbutton(self, label, action):
            """Dynamic JButton creation

            Parameters
            ----------
            label : str
                set text and tooltip
            action : actionPerformed
                the action in the class to be performed

            Returns
            -------
            JButton
                java swing JButton
            """
            jbutton = self.jbutton = JButton()
            jbutton.setFont(Font("Tahoma", 0, 14))
            jbutton.setText(label)
            jbutton.setToolTipText(label)
            jbutton.actionPerformed = action
            jbutton.setHorizontalTextPosition(SwingConstants.CENTER)

            return jbutton

        def create_jlist(self, label, values=None, mode=ListSelectionModel.MULTIPLE_INTERVAL_SELECTION):
            """Dynamic JList creation

            Parameters
            ----------
            label : str
                set text and tooltip
            values : OrderedDict, optional
                ordered dictionary, by default None
            mode : ListSelectionModel, optional
                define JList selection method, by default ListSelectionModel.MULTIPLE_INTERVAL_SELECTION

            Returns
            -------
            JList
                java swing JList
            """
            jlist = self.jlist = JList(sorted(values))
            jlist.setFont(Font("Tahoma", 0, 14))
            jlist.setSelectionMode(mode)
            jlist.setToolTipText(label)
            jlist.setBorder(
                BorderFactory.createTitledBorder(
                    None, label, 2, 2, Font("Tahoma", 0, 14)
                )
            )
            return jlist

        def run(self):
            """Invloke
            """
            self.outer_class = Cumulus()

            if self.outer_class.cumulus_configs is None:
                JOptionPane.showMessageDialog(
                    None,
                    "No configuration file path provided\n\nExiting program",
                    "Missing Configuration File",
                    JOptionPane.ERROR_MESSAGE,
                )

            self.configurations = DictConfig(self.outer_class.cumulus_configs).read()

            self.outer_class.go_config["StdOut"] = "true"
            self.outer_class.go_config["Subcommand"] = "get"
            self.outer_class.go_config["Endpoint"] = "watersheds"

            ps_out, ws_out = self.outer_class.get_metadata()
            self.api_watersheds = watershed_refactor(ws_out) if ws_out else {}
            self.api_products = product_refactor(ps_out) if ps_out else {}

            frame = JFrame("Cumulus Configuration")
            frame.setDefaultCloseOperation(JFrame.DISPOSE_ON_CLOSE)
            frame.setAlwaysOnTop(False)
            frame.setIconImage(ImageIcon(CLOUD_ICON).getImage())
            frame.setLocation(Point(10, 10))
            frame.setLocationByPlatform(True)
            frame.setName("CumulusCaviUI")
            frame.setResizable(True)
            content_pane = frame.getContentPane()

            # create lists
            self.watershed_list = self.create_jlist(
                "Watersheds", self.api_watersheds, ListSelectionModel.SINGLE_SELECTION)
            self.product_list = self.create_jlist("Products", self.api_products)
            # create buttons
            select_button = self.create_jbutton("...", self.select)
            execute_button = self.create_jbutton("Save and Execute Configuration", self.execute)
            save_button = self.create_jbutton("Save Configuration", self.save)
            # create label
            label = self.label = JLabel()
            label.setFont(Font("Tahoma", 0, 14))
            label.setText("DSS File Downloads")
            # create text field
            dsspath = self.dsspath = JTextField()
            dsspath.setFont(Font("Tahoma", 0, 14))
            dsspath.setToolTipText("FQPN to output file (.dss)")
            # create scroll pane
            jScrollPane1 = JScrollPane()
            jScrollPane2 = JScrollPane()
            jScrollPane1.setViewportView(self.product_list)
            jScrollPane2.setViewportView(self.watershed_list)

            try:
                dsspath.setText(self.configurations["dss"])
                idxs = product_index(
                    self.configurations["product_ids"], self.api_products
                )
                self.product_list.setSelectedIndices(idxs)
                idx = watershed_index(
                    self.configurations["watershed_id"], self.api_watersheds
                )
                self.watershed_list.setSelectedIndex(idx)
            except KeyError as ex:
                print("KeyError: missing {}".format(ex))

            # autopep8: off
            # pylint: disable=bad-continuation, line-too-long
            layout = GroupLayout(content_pane)
            content_pane.setLayout(layout)
            layout.setHorizontalGroup(
                layout.createParallelGroup(GroupLayout.Alignment.LEADING)
                .addGroup(layout.createSequentialGroup()
                    .addContainerGap()
                    .addGroup(layout.createParallelGroup(GroupLayout.Alignment.LEADING)
                        .addComponent(jScrollPane1, GroupLayout.DEFAULT_SIZE, 480, Short.MAX_VALUE)
                        .addComponent(jScrollPane2)
                        .addGroup(layout.createSequentialGroup()
                            .addComponent(dsspath)
                            .addPreferredGap(LayoutStyle.ComponentPlacement.RELATED)
                            .addComponent(select_button))
                        .addGroup(layout.createSequentialGroup()
                            .addComponent(label)
                            .addGap(0, 0, Short.MAX_VALUE))
                        .addGroup(layout.createSequentialGroup()
                            .addGap(0, 0, Short.MAX_VALUE)
                            .addComponent(execute_button, GroupLayout.PREFERRED_SIZE, GroupLayout.DEFAULT_SIZE, GroupLayout.PREFERRED_SIZE)
                            .addGap(18, 18, 18)
                            .addComponent(save_button, GroupLayout.PREFERRED_SIZE, GroupLayout.DEFAULT_SIZE, GroupLayout.PREFERRED_SIZE)))
                    .addContainerGap())
            )
            layout.setVerticalGroup(
                layout.createParallelGroup(GroupLayout.Alignment.LEADING)
                .addGroup(layout.createSequentialGroup()
                    .addContainerGap()
                    .addComponent(jScrollPane2, GroupLayout.PREFERRED_SIZE, 200, GroupLayout.PREFERRED_SIZE)
                    .addPreferredGap(LayoutStyle.ComponentPlacement.UNRELATED)
                    .addComponent(jScrollPane1, GroupLayout.DEFAULT_SIZE, 222, Short.MAX_VALUE)
                    .addPreferredGap(LayoutStyle.ComponentPlacement.RELATED)
                    .addComponent(label)
                    .addPreferredGap(LayoutStyle.ComponentPlacement.RELATED)
                    .addGroup(layout.createParallelGroup(GroupLayout.Alignment.BASELINE)
                        .addComponent(dsspath, GroupLayout.PREFERRED_SIZE, GroupLayout.DEFAULT_SIZE, GroupLayout.PREFERRED_SIZE)
                        .addComponent(select_button))
                    .addPreferredGap(LayoutStyle.ComponentPlacement.RELATED)
                    .addGroup(layout.createParallelGroup(GroupLayout.Alignment.BASELINE)
                        .addComponent(execute_button, GroupLayout.PREFERRED_SIZE, GroupLayout.DEFAULT_SIZE, GroupLayout.PREFERRED_SIZE)
                        .addComponent(save_button, GroupLayout.PREFERRED_SIZE, GroupLayout.DEFAULT_SIZE, GroupLayout.PREFERRED_SIZE))
                    .addContainerGap())
            )
            # pylint: enable=bad-continuation, line-too-long
            # autopep8: on

            frame.pack()
            frame.setLocationRelativeTo(None)

            frame.setVisible(True)
