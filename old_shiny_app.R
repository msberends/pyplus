#' Launch the ShinyPLUS App
#'
#' Starts the Shiny application for weekly grocery planning, including features for meal selection, fixed and extra products, basket management, and integration with PLUS.nl.
#' @param credentials Path to a YAML file containing at least fields `email` and `shinyplus_password`, or a [list] contains those names. Can be set with `options(plus_credentials = "...")`
#' @details
#' The `shinyplus()` function launches a multi-tab Shiny application with the following core components:
#'
#' - **Weekmenu**: Allows users to select dishes for each day of the week. Each dish is linked to ingredients, which can be automatically added to the grocery basket.
#' - **Vaste boodschappen**: Users can maintain and select from a list of fixed (recurring) products. Selected quantities are added to the basket.
#' - **Extra artikelen**: Users can manually search and add additional products not linked to meals or fixed lists.
#' - **Mandje**: A complete overview of all selected products is shown, grouped by label. Users can adjust quantities or remove items. The basket can then be sent to the online PLUS.nl shopping cart.
#' - **PLUS Winkelwagen**: Displays the current contents of the user's PLUS.nl online cart, including quantities, prices, and product images. Includes a checkout button.
#' - **Gerechten beheren**: Users can create and manage custom dishes, define their preparation details, and assign ingredients from the product list.
#' - **Inloggen**: Supports login to PLUS.nl using [`Chromote`][chromote::Chromote] automation. This is required for sending the basket to the online cart or retrieving cart contents.
#'
#' ### Getting Started:
#' 1. Create an account at <https://www.plus.nl> and select your preferred local store.
#' 2. Save your PLUS.nl login credentials in a `.yaml` file with `email` and `password` fields. Set an app password in the same file for a `shinyplus_password` field.
#' 3. Set the file path in your R session using:
#'
#'    ```r
#'    options(plus_credentials = "path/to/your_file.yaml")
#'    ```
#' 4. Generate a local product list using `shinyplus::update_product_list_from_html()` (see its documentation for detailed steps).
#' 5. Launch the app with:
#'
#'    ```r
#'    shinyplus::shinyplus()
#'    ```
#'
#' All user-specific data (e.g. dishes, baskets, fixed products) is saved locally as `.rds` files per user.
#' @importFrom shiny a actionButton addResourcePath br checkboxGroupInput checkboxInput column conditionalPanel div fluidPage fluidRow h3 h4 h5 h6 hr HTML icon img isolate modalButton modalDialog navbarPage numericInput observe observeEvent p passwordInput radioButtons reactive reactiveVal reactiveValues removeModal renderUI req selectInput selectizeInput shinyApp showModal showNotification span strong tabPanel tagList tags textAreaInput textInput uiOutput updateActionButton updateCheckboxGroupInput updateCheckboxInput updateNumericInput updateRadioButtons updateSelectInput updateSelectizeInput updateTextAreaInput updateTextInput wellPanel withProgress incProgress tabsetPanel
#' @importFrom bslib bs_theme font_google card
#' @importFrom dplyr filter pull mutate select arrange desc inner_join bind_rows distinct if_else left_join count row_number slice
#' @importFrom tibble tibble as_tibble
#' @importFrom DT datatable DTOutput renderDT formatCurrency
#' @importFrom cli symbol
#' @importFrom shinyjs hide show useShinyjs runjs disable enable
#' @importFrom commonmark markdown_html markdown_text
#' @importFrom rvest read_html html_elements html_element html_text2
#' @importFrom calendar ic_event ic_attributes_vec ical ic_write
#' @importFrom sortable sortable_js sortable_options
#' @importFrom purrr map_chr
#' @encoding UTF-8
#' @inheritSection shinyplus-package Disclaimer
#' @export
shinyplus <- function(credentials = getOption("plus_credentials")) {

  get_credentials(credentials, require_fields = c("email", "shinyplus_password"))

  weekdays_list <- c("Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag")
  weekdays_list_full <- c(weekdays_list, paste0("lunch", 1:5))

  addResourcePath("shinyplus-assets", system.file(package = "shinyplus"))

  ui <- fluidPage(
    useShinyjs(),
    tags$head(
      tags$title("ShinyPLUS"),
      tags$link(rel = "icon", type = "image/x-icon", href = "shinyplus-assets/favicon.ico")
    ),
    tags$script(HTML("
      Shiny.addCustomMessageHandler('updateSelectizeDishList', function(message) {
        var input = $('#' + message.inputId)[0];
        if (input && input.selectize) {
          input.selectize.clearOptions();
          message.choices.forEach(function(opt) {
            input.selectize.addOption(opt);
          });
          input.selectize.refreshOptions(false);
        }
      });
    ")),
    tags$script(HTML("
      Shiny.addCustomMessageHandler('updateSelectizeProductList', function(message) {
        var input = $('#' + message.inputId)[0];
        if (input && input.selectize) {
          input.selectize.clearOptions();
          message.choices.forEach(function(opt) {
            input.selectize.addOption(opt);
          });
          input.selectize.refreshOptions(false);
        }
      });
    ")),
    tags$script(HTML("
      Shiny.addCustomMessageHandler('updateBasketCount', function(count) {
        document.getElementById('basket-count').textContent = count;
      });
    ")),
    tags$script(HTML('
      Shiny.addCustomMessageHandler("get_element_content", function(id) {
        const el = document.getElementById(id);
        if (el) {
          Shiny.setInputValue(id + "_content", el.innerHTML, {priority: "event"});
        } else {
          Shiny.setInputValue(id + "_content", null);
        }
      });
    ')),
    tags$script(HTML("
      (function waitForImagePreview() {
        const preview = document.getElementById('imagePreview');
        if (!preview) {
          setTimeout(waitForImagePreview, 100); // wait and retry
          return;
        }

        document.addEventListener('mousemove', function (e) {
          if (preview.style.display === 'block') {
            preview.style.left = (e.pageX + 10) + 'px';
            preview.style.top = (e.pageY + 10) + 'px';
          }
        });

        document.addEventListener('mouseover', function (e) {
          const target = e.target.closest('img.hover-preview');
          if (!target) return;

          preview.src = target.src;
          preview.style.display = 'block';
        });

        document.addEventListener('mouseout', function (e) {
          const target = e.target.closest('img.hover-preview');
          if (!target) return;

          preview.style.display = 'none';
        });
      })();
    ")),
    tags$script(HTML("
      Shiny.addCustomMessageHandler('openPlainTextTab', function(message) {
        var win = window.open('', '_blank');
        if (win) {
          win.document.write('<pre>' + message + '</pre>');
          win.document.close();
        } else {
          alert('Pop-up blocked. Please allow pop-ups for this site.');
        }
      });
    ")),
    tags$style(HTML("
      :root {
        --plus-red-rgb: 227, 19, 29;
        --plus-green-light-rgb: 128, 189, 29;
        --plus-green-dark-rgb: 34, 118, 71;
        --plus-purple-rgb: 85, 77, 167;

        --plus-red: rgb(var(--plus-red-rgb));
        --plus-green-light: rgb(var(--plus-green-light-rgb));
        --plus-green-dark: rgb(var(--plus-green-dark-rgb));
        --plus-purple: rgb(var(--plus-purple-rgb));

        --bs-primary-rgb: var(--plus-green-light-rgb);
        --bs-secondary-rgb: var(--plus-purple-rgb);
        --bs-danger-rgb: var(--plus-red-rgb);
        --bs-link-color: var(--plus-purple);
        --bs-link-hover-color: var(--plus-purple);
      }

      .text-danger {
        color: var(--plus-red) !important;
      }
      .text-primary {
        color: var(--plus-purple) !important;
      }
      .text-secondary {
        color: var(--plus-green-light) !important;
      }
      .text-success {
        color: var(--plus-green-light) !important;
      }

      #imagePreview {
        position: absolute;
        max-width: 600px;
        max-height: 400px;
        pointer-events: none;
        display: none;
        padding: 8px;
        border-radius: 12px;
        background: rgba(255, 255, 255, 0.3); /* translucent */
        backdrop-filter: blur(12px); /* macOS-style blur */
        -webkit-backdrop-filter: blur(12px); /* for Safari */
        border: 1px solid rgba(255, 255, 255, 0.5);
        z-index: 9999;
      }
      @media (max-width: 575.98px) {
        #imagePreview {
          display: none !important;
        }
      }

      .navbar {
        background: none;
      }
      .nav-tabs {
        margin-bottom: 1%;
      }
      hr {
        margin: 1rem 0;
      }
      .well hr {
        margin: 2rem 0;
      }

      .selectize-dropdown .highlight {
        background: color-mix(in srgb, var(--plus-green-light) 25%, white) !important;
      }

      .btn_make_optional {
        padding: 0px 5px 0px 5px;
        font-size: 0.7rem;
        margin-left: 10px;
      }

      #basket-icon-wrapper {
        position: absolute;
        top: 10px;
        right: 20px;
        font-size: 2rem;
        z-index: 999;
      }

      .btn-danger {
        background: var(--plus-red);
        border-color: var(--plus-red);
      }
      .btn-danger:hover, .btn-danger:active, .btn-danger:focus {
        background: color-mix(in srgb, var(--plus-red) 70%, black);
        border-color: var(--plus-red);
      }
      .btn-success {
        background: var(--plus-green-light);
        border-color: var(--plus-green-light);
      }
      .btn-success:hover, .btn-success:active, .btn-success:focus {
        background: color-mix(in srgb, var(--plus-green-light) 70%, black);
        border-color: var(--plus-green-light);
      }
      .btn-green-dark {
        background: var(--plus-green-dark);
        border-color: var(--plus-green-dark);
      }
      .btn-green-dark:hover, .btn-green-dark:active, .btn-green-dark:focus {
        background: color-mix(in srgb, var(--plus-green-dark) 70%, black);
        border-color: var(--plus-green-dark);
      }
      .btn-primary {
        background: var(--plus-purple);
        border-color: var(--plus-purple);
      }
      .btn-primary:hover, .btn-primary:active, .btn-primary:focus {
        background: color-mix(in srgb, var(--plus-purple) 70%, black);
        border-color: var(--plus-purple);
      }
      .shiny-notification {
        color: white;
        background: var(--plus-purple);
      }
      .shiny-notification-message {
        color: white;
        background: var(--plus-green-light);
      }
      .shiny-notification-error {
        color: white;
        background: var(--plus-red);
      }
      a {
        color: var(--plus-purple);
      }
      a:hover, a:active, a:focus {
        color: color-mix(in srgb, var(--plus-purple) 70%, black);
      }

      .shiny-input-container .checkbox input:checked,
      .shiny-input-container .radio input:checked {
        background-color: var(--plus-purple);
        border-color: var(--plus-purple);
      }
      .shiny-input-container input:focus {
        box-shadow: none !important;
      }
      .selectize-dropdown .selected {
        background-color: var(--plus-purple);
      }

      #column-weekmenu .bslib-card {
        background: color-mix(in srgb, var(--plus-green-light) 3%, white);
      }
      #column-weekmenu .bslib-card h3,
      #column-weekmenu .bslib-card h5 {
        color: var(--plus-green-light);
      }
      #column-weekmenu .btn:hover {
        background-color: color-mix(in srgb, var(--plus-green-light) 25%, white);
        border-color: inherit;
        color: inherit;
      }
      #column-sale .bslib-card {
        background: color-mix(in srgb, var(--plus-red) 3%, white);
      }
      #column-sale #sale-list {
        background: color-mix(in srgb, var(--plus-red) 1%, white);
      }
      #column-sale .bslib-card h3,
      #column-sale .bslib-card h5 {
        color: var(--plus-red);
      }
      #column-sale .btn:hover {
        background-color: color-mix(in srgb, var(--plus-red) 25%, white);
        border-color: inherit;
        color: inherit;
      }
      #column-fixed .bslib-card {
        background: color-mix(in srgb, var(--plus-purple) 3%, white);
      }
      #column-fixed .bslib-card h3,
      #column-fixed .bslib-card h5,
      #column-fixed .bslib-card h6 {
        color: var(--plus-purple);
      }
      #column-fixed #fixed_items_ui h6 {
        border-bottom: 1px dashed var(--plus-purple);
        padding-bottom: 5px;
      }
      #column-fixed .btn:hover {
        background-color: color-mix(in srgb, var(--plus-purple) 25%, white);
        border-color: inherit;
        color: inherit;
      }
      #column-fixed .div-fixed-expanded {
        height: 300px;
      }
      #column-basket .bslib-card {
        background: color-mix(in srgb, var(--plus-green-dark) 3%, white);
      }
      #column-basket .bslib-card h3,
      #column-basket .bslib-card h5 {
        color: var(--plus-green-dark);
      }
      #column-cart .bslib-card {
        background: color-mix(in srgb, var(--plus-green-light) 3%, white);
        height: calc(100vh - 200px);
      }
      #column-cart .bslib-card h3,
      #column-cart .bslib-card h5 {
        color: var(--plus-green-light);
      }
      #column-cart .btn:hover {
        background-color: color-mix(in srgb, var(--plus-green-light) 25%, white);
        border-color: inherit;
        color: inherit;
      }

      .flexible-item .selectize-input {
        border-color: var(--plus-purple);
        color: var(--plus-purple);
      }
      .optional-item .checkbox input:checked {
        background-color: var(--plus-green-light);
        border-color: var(--plus-green-light);
      }

      .well {
        background: rgba(255, 255, 255, 0.7);
        color: RGB(var(--bs-emphasis-color-rgb, 0, 0, 0));
        border-radius: 10px;
      }

      .products-list-row {
        height: 75px;
        display: flex;
        align-items: center;
        margin-bottom: 5px;
      }

      .products-list-img img {
        max-height: 70px;
        max-width: 100%;
        object-fit: contain;
      }

      .products-list-p p {
        margin: 0;
        font-size: 0.95rem;
        display: inline-block;
        line-height: 1.2;
      }

      .basket-label {
        font-size: 0.7em;
        margin-left: 5px;
        padding-left: 5px;
        padding-right: 5px;
        border-radius: 5px;
      }
      .basket-count-icon {
        color: var(--plus-green-dark);
      }
      #dish_ingredients_table .basket-label {
        top: -2px;
        position: relative;
        padding-bottom: 1px;
      }

      .products-list-p .basket-label.weekmenu {
        color: white;
        background: var(--plus-green-light);
        border: 1px solid var(--plus-green-light);
      }
      .products-list-p .basket-label.sale {
        color: white;
        background: var(--plus-red);
        border: 1px solid var(--plus-red);
      }
      .products-list-p .basket-label.fixed {
        color: white;
        background: var(--plus-purple);
        border: 1px solid var(--plus-purple);
      }
      .products-list-p .basket-label.extra {
        color: white;
        background: var(--plus-green-dark);
        border: 1px solid var(--plus-green-dark);
      }

      .products-list-qty {
        padding-top: 10px;
      }

      .products-list-qty .form-control {
        height: 35px;
        padding: 5px;
      }

      .fixed_trash_icon button {
        font-size: 0.8rem;
        line-height: 2;
      }
      #add_fixed_heading {
        line-height: 0.5;
      }
      .fixed-heading-collapsed {
        height: 24px;
        margin-top: 32px;
      }
      #fixed_items_ui > .fixed-heading-collapsed:first-child {
        margin-top: -10px;
      }

      .products-list-order {
        margin-top: -10px;
      }
      .products-list-order button {
        height: 24px;
        font-size: 0.5rem;
      }


      @media (max-width: 575.98px) {
        .nav-tabs, .nav-tabs * {
          width: 100%;
          padding: 0;
          border: none !important;
          margin-bottom: 2%;
        }
        .nav-item {
          text-align: center;
        }
        .nav-link.active {
          border-bottom: none;
        }

        .products-list-row {
          display: flex;
          flex-direction: row;
          flex-wrap: nowrap;
          align-items: flex-start;
          height: 70px;
        }

        .product-list-col1 {
          width: 25%;
          padding-right: 5px;
          margin-top: auto;
          margin-bottom: auto;
        }

        .product-list-col2 {
          width: 50%;
          margin-top: auto;
          margin-bottom: auto;
        }

        #column-basket .product-list-col2,
        #column-fixed .product-list-col2 {
          width: 43%;
        }
        #column-fixed .fixed-heading {
          width: 68%;
        }

        #dish_ingredients_table .product-list-col2 {
          width: 60%;
        }

        .product-list-col3 {
          width: 25%;
          display: flex;
          align-items: flex-start;
          padding-top: 5px;
        }

        #column-fixed .products-list-order {
          margin-top: -16px;
        }
        #column-fixed .fixed-heading {
          margin-top: 21px;
        }
        #column-fixed .fixed_trash_icon {
          margin-top: 17px;
          padding-left: 10.5%;
        }

        #column-basket .product-list-col3,
        #column-fixed .product-list-col3 {
         width: 20%;
        }

        #dish_ingredients_table .product-list-col3 {
         width: 15%;
          margin-top: auto;
          margin-bottom: auto;
        }

        .product-list-col4 {
          width: 10%;
          margin-top: 23px;
          margin-left: -5px;
        }

        .products-list-qty {
          width: 100%;
        }

        .products-list-qty .form-group {
          width: 100%;
          margin-bottom: 0;
        }

        .products-list-p p {
          font-size: 0.9rem;
          line-height: 1.3;
          margin-bottom: 6px;
        }
      }


      .dish-selector .selectize-dropdown .option {
        padding: 6px 12px !important;  /* More left/right padding */
        font-weight: normal !important;  /* Not bold */
      }

      .dish-selector .selectize-dropdown .option:hover,
      .dish-selector .selectize-dropdown .option.active {
        background-color: #f0f0f0 !important;  /* Minimalist grey */
        color: #000 !important;
      }

      .dish-selector .selectize-input, .selectize-dropdown {
        font-size: 0.9rem;
      }

      .extra-input-row .selectize-control,
      .extra-input-row .form-control {
        font-size: 0.85rem;
      }

      .card.stretch-with-margin {
        margin-bottom: 300px;
      }

      .selectize-dropdown-content {
        max-height: 500px !important;  /* same as .card.stretch-with-margin */
      }

      #column-sale {
        display: flex;
        flex-direction: column;
        height: calc(100vh - 100px);
        overflow: hidden;
      }
      #sale-list {
        flex-grow: 1;
        overflow-y: auto;
        min-height: 0; /* required for flex child to shrink correctly */
        margin-bottom: 1rem;
      }
      #column-sale > .card:first-child {
        flex-shrink: 0;
      }

      .sale-card {
        padding: 12px;
        text-align: center;
        height: 100%;
        border-bottom: 1px solid #eee;
        padding-top: 24px;
      }
      .sale-img {
        height: 120px;
        max-width: 100px;
        margin-bottom: 10px;
      }
      .sale-txt {
        color: var(--plus-red);
        font-size: 0.85rem;
        margin-bottom: 5px;
        background-color: color-mix(in srgb, var(--plus-red) 10%, white);
        border-radius: 10px;
        width: 90%;
        margin-left: 5%;
      }
      .sale-name {
        font-size: 0.85rem;
      }
      .sale-unit {
        color: grey;
        font-size: 0.8rem;
        margin-bottom: 8px;
      }
      .sale-qty * {
        text-align: center;
      }
      .sale-single-label {
        width: 100%;
        background: color-mix(in srgb, var(--plus-purple) 15%, white);
        text-align: center;
        padding: 2rem;
        font-size: 1.25rem;
        border-radius: 30px;
        margin-top: 20px;
        margin-bottom: 20px;
      }
      .sale-single-label a {
        font-style: italic;
        text-decoration: none;
      }
      .sale-single-label a:hover {
        font-style: italic;
        text-decoration: underline;
      }
      .sale-group-title {
        color: black !important;
        margin: 20px;
      }

      .price-line {
        margin-top: 5px;
      }
      .price-current {
        font-size: 1.1rem;
        color: var(--plus-red);
        margin-right: 4px;
      }
      .price-previous {
        text-decoration: line-through;
        color: grey;
        font-size: 0.9rem;
      }

      .product-qty, .card-text {
        color: grey;
        font-size: 0.9em;
      }

      #online_cart_table td:nth-child(6) {
        font-weight: bold;
      }

      #dish_instructions_ui h1 {
        font-size: 1.5rem;
      }
      #dish_instructions_ui h2 {
        font-size: 1.25rem;
      }
      #dish_instructions_ui h3 {
        font-size: 1.15rem;
      }
      #dish_instructions_ui h4,
      #dish_instructions_ui h5,
      #dish_instructions_ui h6 {
        font-size: 100%;
      }
      .dish_instructions_text {
        padding: 5px;
        font-size: 85% !important;
      }
    ")),
    tags$img(id = "imagePreview"), # preview image element
    theme = bs_theme(version = 5, base_font = font_google("Open Sans")),
    navbarPage(
      title = div(
        img(src = "shinyplus-assets/shinylogo.png", height = "40px", style = "margin-right: 10px;"),
        span(
          id = "basket-icon-wrapper",
          icon("basket-shopping", class = "basket-count-icon"),
          span(id = "basket-count", class = "badge badge-danger", style = "position: absolute; top: 5px; right: -4px; background: var(--plus-red); color: white; border-radius: 50%; padding: 4px 7px; font-size: 0.75rem;", "0")
        )
      ),
      tabPanel("Boodschappen doen",  # UI: Boodschappen ----
               tabsetPanel(
                 tabPanel("Weekmenu, aanbiedingen en vaste boodschappen",
                          fluidPage(
                            fluidRow(
                              column(3, id = "column-weekmenu",
                                     card(h3("1. Weekmenu"),
                                          fluidRow(
                                            column(6, actionButton("add_weekmenu_products_to_basket", "Toevoegen aan mandje", icon = icon("basket-shopping"), width = "100%")),
                                            column(6, actionButton("weekmenu_clear", "Weekmenu leegmaken", icon = icon("rotate-left"), width = "100%")),
                                          ),
                                          fluidRow(
                                            column(6, actionButton("ics_weekmenu", "In agenda plaatsen", icon = icon("calendar-days"), width = "100%")),
                                            column(6, actionButton("email_weekmenu", "Overzicht e-mailen", icon = icon("envelope"), width = "100%"))),
                                          div(class = "dish-selector",
                                              h5("Avondeten"),
                                              lapply(weekdays_list, function(day) {
                                                selectizeInput(
                                                  inputId = paste0("dish_day_", day),
                                                  label = day,
                                                  width = "100%",
                                                  choices = NULL,
                                                  options = list(
                                                    create = TRUE,
                                                    render = I("
                                                      {
                                                        option_create: function(data, escape) {
                                                          return '<div class=\"create\">Voeg <strong>' +
                                                                 escape(data.input) +
                                                                 '</strong> toe als nieuw gerecht...</div>';
                                                        },
                                                        option: function(item, escape) {
                                                          return '<div style=\"padding-left: 5px;\">' +
                                                                 '' + escape(item.label) + '<br>' +
                                                                 '<small style=\"opacity: 0.8; padding-left: 20px;\">' +
                                                                 item.subtext + '</small>' +
                                                                 '</div>';
                                                        },
                                                        item: function(item, escape) {
                                                          return '<div>' + escape(item.label) + '</div>';
                                                        }
                                                      }
                                                   "))
                                                )
                                              })
                                          ),
                                          # actionButton("weekmenu_refresh", "Willekeurige keuze", icon = icon("rotate"), width = "100%"),
                                          div(class = "dish-selector",
                                              h5("Lunch / Anders"),
                                              lapply(paste0("lunch", 1:5), function(day) {
                                                selectizeInput(
                                                  inputId = paste0("dish_day_", day),
                                                  label = NULL,
                                                  width = "100%",
                                                  choices = NULL,
                                                  options = list(
                                                    render = I("
                                                     {
                                                       option: function(item, escape) {
                                                         return '<div style=\"padding-left: 5px;\">' +
                                                                  '' + escape(item.label) + '<br>' +
                                                                  '<small style=\"opacity: 0.8; padding-left: 20px;\">' +
                                                                  item.subtext + '</small>' +
                                                                '</div>';
                                                       },
                                                       item: function(item, escape) {
                                                         return '<div>' + escape(item.label) + '</div>';
                                                       }
                                                     }
                                                   "))
                                                )
                                              })
                                          ),
                                          hr(),
                                          radioButtons("sort_dishes", "Gerechten sorteren op", choices = c("Naam", "Bereidingstijd", "Hoeveelheid groenten", "Type vlees/vis/vega"), selected = "Naam", width = "100%")
                                     )
                              ),
                              column(5, id = "column-sale",
                                     card(h3("2. Aanbiedingen"),
                                          div(id = "loading_spinner", style = "display:none;", p("Bezig met ophalen van aanbiedingen...")),
                                          uiOutput("sale_header_ui")
                                     ),
                                     card(id = "sale-list",
                                          uiOutput("sale_items_ui")
                                     )
                              ),
                              column(4, id = "column-fixed",
                                     card(h3("3. Vaste boodschappen"),
                                          fluidRow(
                                            column(6, actionButton("add_fixed_to_basket", "Toevoegen aan mandje", icon = icon("basket-shopping"), width = "100%")),
                                            column(6, actionButton("fixed_to_zero", "Alles op nul zetten", icon = icon("rotate-left"), width = "100%")),
                                          ),
                                          uiOutput("fixed_items_ui"),
                                          hr(),
                                          selectizeInput('add_fixed_product', NULL,
                                                         choices = NULL,
                                                         width = "100%",
                                                         options = list(
                                                           placeholder = "Type om te zoeken...",
                                                           maxOptions = 25,
                                                           dropdownParent = "body",
                                                           onInitialize = I('function() { this.setValue(""); }'),
                                                           inputAttr = list(
                                                             autocomplete = "off",
                                                             autocorrect = "off",
                                                             autocapitalize = "off",
                                                             spellcheck = "false"
                                                           ),
                                                           render = I("{
                                                             option: function(item, escape) {
                                                               return '<div class=\"product-option\" style=\"display: flex; align-items: center; height: 50px;\">' +
                                                                        '<img class=\"hover-preview\" src=\"' + escape(item.img) + '\" style=\"height: 40px; width: 40px; object-fit: contain; margin-right: 10px;\" />' +
                                                                        '<div style=\"flex: 1; min-width: 0;\">' +
                                                                          '<div style=\"font-weight: normal; text-align: left;\">' + escape(item.label) + '</div>' +
                                                                          '<div style=\"color: grey; font-size: 0.8em; text-align: left;\">' + escape(item.subtext) + '</div>' +
                                                                        '</div>' +
                                                                      '</div>';
                                                             },
                                                             item: function(item, escape) {
                                                               return '<div>' + escape(item.label) + '</div>';
                                                             }
                                                           }")
                                                         )
                                          ),
                                          uiOutput("fixed_settings_ui")
                                     )
                              )
                            )
                          )
                 ),
                 tabPanel(HTML(paste0(icon("basket-shopping"), " Mandje en ", icon("cart-shopping"), " PLUS Winkelwagen")),
                          fluidPage(
                            fluidRow(
                              column(6, id = "column-basket",
                                     card(class = "stretch-with-margin",
                                          h3(HTML(paste0(icon("basket-shopping"), " Mandje"))),
                                          selectizeInput('add_extra_product', "Extra artikel toevoegen:",
                                                         choices = NULL,
                                                         width = "100%",
                                                         options = list(
                                                           placeholder = "Type om te zoeken...",
                                                           maxOptions = 25,
                                                           dropdownParent = "body",
                                                           onInitialize = I('function() { this.setValue(""); }'),
                                                           inputAttr = list(
                                                             autocomplete = "off",
                                                             autocorrect = "off",
                                                             autocapitalize = "off",
                                                             spellcheck = "false"
                                                           ),
                                                           render = I("{
                                                            option: function(item, escape) {
                                                              return '<div class=\"product-option\" style=\"display: flex; align-items: center; height: 50px;\">' +
                                                                       '<img src=\"' + escape(item.img) + '\" style=\"height: 40px; width: 40px; object-fit: contain; margin-right: 10px;\" />' +
                                                                       '<div style=\"flex: 1; min-width: 0;\">' +
                                                                         '<div style=\"font-weight: normal; text-align: left;\">' + escape(item.label) + '</div>' +
                                                                         '<div style=\"color: grey; font-size: 0.8em; text-align: left;\">' + escape(item.subtext) + '</div>' +
                                                                       '</div>' +
                                                                     '</div>';
                                                            },
                                                            item: function(item, escape) {
                                                              return '<div>' + escape(item.label) + '</div>';
                                                            }
                                                          }")
                                                         )),
                                          uiOutput("basket_overview_table"),
                                          hr(),
                                          fluidRow(
                                            column(3, actionButton("sort_basket_name", "Op naam", icon = icon("arrow-down-a-z"), width = "100%")),
                                            column(3, actionButton("sort_basket_label", "Op label", icon = icon("arrow-down-short-wide"), width = "100%")),
                                            column(3, actionButton("sort_basket_quantity", "Op aantal", icon = icon("arrow-down-1-9"), width = "100%")),
                                            column(3, actionButton("email_basket", "E-mailen", icon = icon("envelope"), width = "100%"))
                                          ),
                                          fluidRow(
                                            column(6, actionButton("send_basket_to_cart", HTML(paste0("Inhoud in ", icon("cart-shopping"), " PLUS Winkelwagen plaatsen")), class = "btn-success", width = "100%")),
                                            column(6, actionButton("clear_basket", "Mandje leegmaken", icon = icon("trash"),  class = "btn-danger", width = "100%")),
                                          ),
                                          fluidRow(
                                            column(6, actionButton("clean_basket", "Mandje opschonen", icon = icon("broom"),  class = "btn-primary", width = "100%")),
                                            column(6, actionButton("text_basket", "Inhoud openen als tekst", icon = icon("align-left"),  class = "btn-success btn-green-dark", width = "100%")),
                                          ),
                                          checkboxInput("remove_cart_from_basket", HTML(paste0("Artikelen direct uit mandje verwijderen die succesvol in ", plus_cart_text(), " geplaatst zijn")), value = FALSE, width = "100%")
                                     )
                              ),
                              column(6, id = "column-cart",
                                     card(h3(HTML(plus_cart_text())),
                                     uiOutput("online_cart_summary"),
                                     br(), br(),
                                     DTOutput("online_cart_table")
                                     ),
                              )
                            )
                          )
                 )
               )
      ),
      tabPanel("Gerechten beheren", # UI: Manage dishes ----
               fluidRow(
                 column(3,
                        wellPanel(
                          h4("Gerecht selecteren"),
                          selectInput("selected_dish", NULL, choices = NULL, width = "100%"),
                          actionButton("delete_dish", "Gerecht verwijderen", icon = icon("trash"), class = "btn-danger", width = "100%"),
                          hr(),
                          h5("Nieuw gerecht"),
                          textInput("new_dish_name", NULL, placeholder = "Naam van het gerecht", width = "100%"),
                          actionButton("new_dish", "Nieuw gerecht", icon = icon("plus"), width = "100%"),
                          # hr(),
                          # h5("Voorkeuren 'Willekeurige keuze'"),
                          # lapply(weekdays_list, function(day) {
                          #   selectizeInput(
                          #     inputId = paste0("prep_time_", day),
                          #     label = paste("Bereidingstijd op", tolower(day)),
                          #     choices = c(NA_integer_, 20, 40, 60, 120) |>
                          #       stats::setNames(c("Geen voorkeur",
                          #                         "0-20 minuten",
                          #                         "20-40 minuten",
                          #                         "40-60 minuten",
                          #                         "60+ minuten")),
                          #     width = "100%")
                          # }),
                        ),
                 ),
                 column(3,
                        wellPanel(
                          h4("Gerecht bewerken"),
                          div(style = "display: none;", numericInput("dish_id", NULL, value = 0)),
                          textInput("dish_name", "Naam gerecht:", width = "100%"),
                          checkboxGroupInput("dish_days", "Geschikt voor:", choices = c("Doordeweeks", "Weekend", "Avondeten", "Lunch / Extra" = "Lunch"), selected = NULL),
                          radioButtons("dish_preptime", "Bereidingstijd:",
                                       choices = c(" ", "20", "40", "60", "120") |>
                                         stats::setNames(c("\U2753", # red question mark
                                                           "0-20 minuten",
                                                           "20-40 minuten",
                                                           "40-60 minuten",
                                                           "60+ minuten")),
                                       inline = FALSE, selected = 20),
                          fluidRow(
                            column(6,
                                   radioButtons("dish_vegetables", "Hoeveelheid groenten:",
                                                choices = c(" ", "0", "1", "2", "3") |>
                                                  stats::setNames(vegetables_icon(c(" ", "0", "1", "2", "3"))),
                                                inline = FALSE,
                                                selected = 0)
                            ),
                            column(6,
                                   radioButtons("dish_meat", "Vlees/vis/vega:",
                                                choices = c(" ", "Vegetarisch", "Kip", "Rund", "Varken", "Vis", "Gecombineerd") |>
                                                  stats::setNames(meat_icon(c(" ", "Vegetarisch", "Kip", "Rund", "Varken", "Vis", "Gecombineerd"))),
                                                inline = FALSE,
                                                selected = "Vegetarisch")
                            )
                          ),
                          uiOutput("dish_instructions_ui"),
                        )
                 ),
                 column(6,
                        wellPanel(
                          h5("Ingredi\U00EBnten bewerken"),
                          fluidRow(
                            column(10, selectizeInput('ingredient_url', "Ingredi\U00EBnt uit de lijst kiezen",
                                                     choices = NULL,
                                                     width = "100%",
                                                     options = list(
                                                       placeholder = "Type om te zoeken...",
                                                       maxOptions = 25,
                                                       dropdownParent = "body",
                                                       onInitialize = I('function() { this.setValue(""); }'),
                                                       inputAttr = list(
                                                         autocomplete = "off",
                                                         autocorrect = "off",
                                                         autocapitalize = "off",
                                                         spellcheck = "false"
                                                       ),
                                                       render = I("{
                                                  option: function(item, escape) {
                                                    return '<div class=\"product-option\" style=\"display: flex; align-items: center; height: 50px;\">' +
                                                             '<img src=\"' + escape(item.img) + '\" style=\"height: 40px; width: 40px; object-fit: contain; margin-right: 10px;\" />' +
                                                             '<div style=\"flex: 1; min-width: 0;\">' +
                                                               '<div style=\"font-weight: normal; text-align: left;\">' + escape(item.label) + '</div>' +
                                                               '<div style=\"color: grey; font-size: 0.8em; text-align: left;\">' + escape(item.subtext) + '</div>' +
                                                             '</div>' +
                                                           '</div>';
                                                  },
                                                  item: function(item, escape) {
                                                    return '<div>' + escape(item.label) + '</div>';
                                                  }
                                                }")
                                                     )),
                                   checkboxInput("ingredient_optional", HTML("Dit is een <span class='text-secondary'>optioneel ingredi\U00EBnt</span>")),
                            ),
                            column(2, numericInput("ingredient_quantity", "Aantal", 1, width = "100%")),
                          ),
                          p(HTML(paste0("<small>Een <span class='text-secondary'>optioneel ingredi\U00EBnt</span> wordt alleen gekozen wanneer dit gerecht aan het <span style='color: var(--plus-green-dark);'>", icon("basket-shopping"), " Mandje</span> wordt toegevoegd en is niet iedere keer nodig.</small>"))),
                          textInput("ingredient_flexible", HTML("<strong>OF:</strong> een <span class='text-primary'>flexibel ingredi\U00EBnt</span> toevoegen"), width = "100%", placeholder = "Instructie/label voor ingredi\U00EBnt..."),
                          p(HTML(paste0("<small>Een <span class='text-primary'>flexibel ingredi\U00EBnt</span> wordt pas gekozen wanneer dit gerecht aan het <span style='color: var(--plus-green-dark);'>", icon("basket-shopping"), " Mandje</span> wordt toegevoegd en kan iedere keer iets anders zijn.</small>"))),
                          actionButton("add_ingredient", "Toevoegen aan gerecht", icon = icon("plus")),
                          hr(),
                          uiOutput("dish_ingredients_table")
                        )
                 )
               )
      ),
      tabPanel("Artikelen toevoegen",  # UI: Add products ----
               fluidRow(
                 column(4,
                        h5("Zoeken op PLUS.nl", class = "text-primary"),
                        textInput("product_search_txt", NULL, placeholder = "Naam van artikel...", width = "100%"),
                        actionButton("product_search_btn", "Zoeken op PLUS.nl", icon = icon("search"), width = "100%"),
                        br(),
                        br(),
                        p(class = "text-danger", "Let op: deze functie kan artikelen toevoegen die niet bij de eigen PLUS beschikbaar zijn en vindt ook alleen de eerste 15-25 resultaten."),
                        br(),
                        hr(),
                        br(),
                        h5("Van zelfgekopieerde HTML-elementen", class = "text-primary"),
                        p("Kopieer de HTML-elementen via het webinfovenster na het zoeken van een product op de PLUS-website."),
                        textAreaInput("product_import_html", NULL, placeholder = "HTML-inhoud...", width = "100%", rows = 3),
                        actionButton("product_import_btn", "HTML-tekst importeren", icon = icon("cloud-arrow-down"), width = "100%"),
                        br(),
                        br(),
                        actionButton("open_searchpage", "Website PLUS.nl openen", icon = icon("right-from-bracket"), class = "btn-success", width = "100%"),
                        br(),
                        br(),
                        hr(),

                 ),
                 column(8,
                        uiOutput("product_search")
                 )
               )
      ),
      tabPanel(title = uiOutput("account_tab_title"), value = "account",  # UI: Login ----
               uiOutput("login_ui")
      )
    )
  )

  server <- function(input, output, session) {

    # keep-alive part
    keep_alive <- shiny::reactiveTimer(intervalMs = 10000, session = shiny::getDefaultReactiveDomain())
    shiny::observe({keep_alive()})

    hide("sale-list")
    hide("add_fixed_product")

    product_list_last_updated <- reactiveVal(Sys.time())
    observeEvent(product_list_last_updated(), {
      # save RDS file
      saveRDS(shinyplus_env$product_list, file = file.path(shinyplus_env$data_dir, "product_list.rds"))

      # update field lists
      shinyplus_env$product_choices <- lapply(seq_len(nrow(shinyplus_env$product_list)), function(i) {
        row <- shinyplus_env$product_list[i, ]
        list(
          value = row$url,
          label = row$name,
          subtext = row$unit,
          img = row$img
        )
      })
      session$sendCustomMessage("updateSelectizeProductList", list(
        inputId = "add_fixed_product",
        choices = shinyplus_env$product_choices))

      session$sendCustomMessage("updateSelectizeProductList", list(
        inputId = "add_extra_product",
        choices = shinyplus_env$product_choices))

      session$sendCustomMessage("updateSelectizeProductList", list(
        inputId = "ingredient_url",
        choices = shinyplus_env$product_choices))
    })

    # Server: Setup ----
    values <- reactiveValues(
      sale_items = NULL,
      dishes = tibble(dish_id = numeric(), name = character(), days = character(), preptime = integer(), vegetables = integer(), meat = character(), instructions = character()),
      dish_ingredients = tibble(dish_id = numeric(), product_url = character(), quantity = numeric(), label = character()),
      weekmenu = NULL,
      fixed_products = character(),
      fixed_items = character(),
      extra_items = character(),
      basket = tibble(product_url = character(), quantity = integer(), label = character()),
      new_dish_name = NULL,
      logged_in = FALSE
    )

    # RDS files for saving
    dishes_file <- reactive({
      req(selected_email())
      file.path(shinyplus_env$data_dir, paste0("dishes-", make.names(selected_email()), ".rds"))
    })
    dish_ingredients_file <- reactive({
      req(selected_email())
      file.path(shinyplus_env$data_dir, paste0("dish_ingredients-", make.names(selected_email()), ".rds"))
    })
    weekmenu_file <- reactive({
      req(selected_email())
      file.path(shinyplus_env$data_dir, paste0("weekmenu-", make.names(selected_email()), ".rds"))
    })
    ics_file <- reactive({
      req(selected_email())
      file.path(shinyplus_env$data_dir, paste0("weekmenu-", make.names(selected_email()), ".ics"))
    })
    fixed_products_file <- reactive({
      req(selected_email())
      file.path(shinyplus_env$data_dir, paste0("fixed_products-", make.names(selected_email()), ".rds"))
    })
    basket_file <- reactive({
      req(selected_email())
      file.path(shinyplus_env$data_dir, paste0("basket-", make.names(selected_email()), ".rds"))
    })

    selected_email <- reactiveVal(NULL)

    # fill in values from RDS files
    observeEvent(selected_email(), {
      if (file.exists(dishes_file())) {
        values$dishes <- readRDS(dishes_file())
        if (!"instructions" %in% colnames(values$dishes)) {
          values$dishes$instructions <- ""
        }
      }
      if (file.exists(dish_ingredients_file())) {
        values$dish_ingredients <- readRDS(dish_ingredients_file())
        if (!"label" %in% colnames(values$dish_ingredients)) {
          values$dish_ingredients$label <- NA_character_
        }
      }
      if (file.exists(weekmenu_file())) {
        values$weekmenu <- readRDS(weekmenu_file())
      }
      if (file.exists(fixed_products_file())) {
        values$fixed_products <- readRDS(fixed_products_file())
      }
      if (file.exists(basket_file())) {
        values$basket <- readRDS(basket_file())
      }
    })

    add_to_basket <- function(product_url, quantity = 1, label = "", on_top = FALSE) {
      if (length(product_url) > 1 && length(quantity) == 1) {
        quantity <- rep(quantity, length(product_url))
      }
      if (length(product_url) != length(quantity)) stop("Mismatched product_url and quantity lengths")

      df <- tibble(product_url, quantity, label) |>
        filter(product_url != "", quantity > 0)

      if (nrow(df) == 0) return(invisible())

      if (on_top == TRUE) {
        new_basket <- bind_rows(df, values$basket)
      } else {
        new_basket <- bind_rows(values$basket, df)
      }

      new_basket <- new_basket |>
        # prevent sorting by using factors
        mutate(product_url = factor(as.character(product_url), levels = unique(product_url), ordered = TRUE)) |>
        group_by(product_url, label) |>
        summarise(quantity = sum(quantity), .groups = "drop")

      # Only update if different
      if (!identical(new_basket, values$basket)) {
        values$basket <- new_basket
      }

      showNotification(paste0(sum(df$quantity, na.rm = TRUE),
                              " artikel", ifelse(sum(df$quantity, na.rm = TRUE) > 1, "en", ""),
                              " aan mandje toegevoegd."),
                       duration = 2)
    }


    # Server: Login ----

    user_selection_modal <- function() {
      modalDialog(
        title = "Selecteer een gebruiker",
        selectInput("selected_user_email", "Kies je e-mailadres",
                    choices = c(shinyplus_env$credentials$email, "Zonder inloggen"),
                    selected = NULL),
        passwordInput("selected_user_password", "ShinyPLUS-wachtwoord"),
        easyClose = FALSE,
        footer = actionButton("confirm_user_email", "Doorgaan", class = "btn-primary")
      )
    }

    observe({
      showModal(user_selection_modal())
    })
    observeEvent(input$confirm_user_email, {
      if (input$selected_user_password != shinyplus_env$credentials$shinyplus_password) {
        showNotification("Incorrect wachtwoord", type = "error")
        return(invisible())
      }
      req(input$selected_user_email)
      shinyplus_env$current_user_email <- trimws(tolower(input$selected_user_email))
      shinyplus_env$current_user_password <- shinyplus_env$credentials$password[which(shinyplus_env$credentials$email == shinyplus_env$current_user_email)]
      selected_email(shinyplus_env$current_user_email)
      removeModal()
    })

    output$account_tab_title <- renderUI({
      logged_in <- values$logged_in
      email <- shinyplus_env$current_user_email
      if (logged_in && !is.null(email)) {
        HTML(paste0("Ingelogd als <strong>", email, "</strong>"))
      } else {
        "Inloggen"
      }
    })

    output$login_ui <- renderUI({
      if (!values$logged_in) {
        tagList(
          p("Gebruik je PLUS inloggegevens om in te loggen."),
          if (is.null(shinyplus_env$current_user_email))
            p(HTML("<small>Maak een account aan op "),
              a("plus.nl",
                href = "https://aanmelden.plus.nl/plus/registration",
                target = "_blank",
                .noWS = "outside"),
              HTML(".</small>"))
          else
            p(HTML("<small>Inloggegevens vooraf ingevuld op basis van instelling <code>plus_credentials</code>.</small>")),
          p(HTML(paste0("Email: <strong>", shinyplus_env$current_user_email, "</strong>"))),
          div(id = "login_buttons",
              passwordInput("login_password", "Wachtwoord", value = shinyplus_env$current_user_password),
              actionButton("do_login", "Inloggen bij PLUS.nl", class = "btn-success", icon = icon("right-to-bracket")),
              hr(),
              actionButton("change_user", "Selecteer andere gebruiker", class = "btn-primary", icon = icon("user-xmark"))
          ),
          p(id = "logging_in", style = "display: none;", "Inloggen...")
        )
      } else {
        tagList(
          strong("Ingelogd als: "), shinyplus_env$current_user_email,
          br(),
          br(),
          actionButton("do_logout", "Uitloggen", class = "btn-danger", icon = icon("right-from-bracket"))
        )
      }
    })

    observeEvent(input$change_user, {
      selected_email(NULL)
      showModal(user_selection_modal())
    })

    observeEvent(values$logged_in, {
      if (values$logged_in) {
        values$online_cart <- plus_current_cart(email = shinyplus_env$current_user_email,
                                                password = shinyplus_env$current_user_password,
                                                info = FALSE)
      }
    })

    observeEvent(input$do_login, {
      hide("login_buttons")
      show("logging_in")
      tryCatch({
        showNotification("Inloggen bij PLUS...")
        plus_login(email = shinyplus_env$current_user_email,
                   password = input$login_password,
                   info = FALSE)
        values$logged_in <- TRUE
        showNotification("Succesvol ingelogd.", type = "message")
      }, error = function(e) {
        show("login_buttons")
        hide("logging_in")
        values$logged_in <- FALSE
        showNotification(
          paste("Inloggen mislukt. Probeer het over een paar seconden opnieuw via de knop 'Inloggen'.\nFoutmelding:", e$message),
          type = "error"
        )
      })
    })

    observeEvent(input$do_logout, {
      plus_logout(info = FALSE)
      values$logged_in <- FALSE
    })


    # Server: Boodschappen ----

    observeEvent(input$ingredient_optional, {
      if (isTRUE(input$ingredient_optional)) {
        disable("ingredient_quantity")
      } else {
        enable("ingredient_quantity")
      }
    })

    ## 1. Weekmenu ----
    get_current_weekmenu_selections <- function() {
      isolate(stats::setNames(lapply(weekdays_list_full, function(day) input[[paste0("dish_day_", day)]]), weekdays_list_full))
    }

    # observer on any weekmenu selection
    lapply(weekdays_list_full, function(day) {
      observeEvent(input[[paste0("dish_day_", day)]], {
        value <- input[[paste0("dish_day_", day)]]
        if (!value %in% values$dishes$name && value != "") {
          # it's a new dish, so add it
          new_id <- generate_dish_id()
          values$dishes <- bind_rows(values$dishes, tibble(
            dish_id = new_id,
            name = value,
            days = "Doordeweeks,Weekend,Avondeten",
            preptime = NA_integer_,
            vegetables = NA_integer_,
            meat = NA_character_,
            instructions = ""
          )) |>
            arrange(name)
          saveRDS(values$dishes, dishes_file())
          showNotification("Gerecht toegevoegd. Bewerk het in menu 'Gerechten beheren'.", type = "message")
        }

        # save any change to weekmenu select
        req(selected_email())
        values$weekmenu <- get_current_weekmenu_selections()
        saveRDS(values$weekmenu, weekmenu_file())
      }, ignoreInit = TRUE)
    })

    rebuild_weekmenu_inputs <- function(sorted_dishes) {
      current_selections <- values$weekmenu

      for (day in weekdays_list_full) {
        # Filter dishes by day-type
        if (day %in% c("Zondag", "Maandag", "Dinsdag", "Woensdag", "Donderdag") || grepl("lunch", day)) {
          dishes <- sorted_dishes |> filter(grepl("Doordeweeks", days))
        } else {
          dishes <- sorted_dishes |> filter(grepl("Weekend", days))
        }
        # Dinner / Lunch
        if (grepl("lunch", day)) {
          dishes <- sorted_dishes |> filter(grepl("Lunch", days))
        } else if (day %in% weekdays_list) {
          dishes <- dishes |> filter(grepl("Avond", days))
        }

        custom_dishes <- unlist(current_selections, use.names = FALSE)
        custom_dishes <- unique(custom_dishes[!custom_dishes %in% dishes$name & custom_dishes != ""])
        if (length(custom_dishes) > 0) {
          dishes <- dishes |>
            bind_rows(tibble(name = custom_dishes))
        }

        if (nrow(dishes) == 0) next

        # Build list of choices with label, value, and subtext
        choices_list <- lapply(seq_len(nrow(dishes)), function(i) {
          dish <- dishes[i, ]
          list(
            label = dish$name,
            value = dish$name,
            subtext = paste0(meat_icon(dish$meat), "&nbsp;&nbsp;", symbol$bullet, "&nbsp;&nbsp;",
                             preptime_icon(dish$preptime), "&nbsp;&nbsp;", symbol$bullet, "&nbsp;&nbsp;",
                             vegetables_icon(dish$vegetables))
          )
        })

        session$sendCustomMessage("updateSelectizeDishList", list(
          inputId = paste0("dish_day_", day),
          choices = choices_list
        ))
        updateSelectInput(session, paste0("dish_day_", day), selected = current_selections[[day]])
      }
    }

    set_random_dish <- function(day, set_filter, df, session) {
      dish <- df |>
        filter({{set_filter}}) |>
        filter(!name %in% shinyplus_env$dishes) |>
        pull(name)
      if (length(dish) > 0) {
        dish <- sample(dish, size = 1)
        shinyplus_env$dishes <- c(shinyplus_env$dishes, dish)
        updateSelectInput(session, paste0("dish_day_", day), selected = dish)
      }
    }

    observeEvent(input$weekmenu_refresh, {
      df <- values$dishes |> filter(grepl("Avondeten", days))
      doordeweeks <- df |> filter(grepl("Doordeweeks", days))
      weekend <- df |> filter(grepl("Weekend", days))

      shinyplus_env$dishes <- ""
      set_random_dish("Maandag", preptime <= 20, doordeweeks, session)
      set_random_dish("Dinsdag", preptime <= 20, doordeweeks, session)
      set_random_dish("Woensdag", preptime <= 60, doordeweeks, session)
      set_random_dish("Donderdag", preptime <= 60, doordeweeks, session)
      set_random_dish("Vrijdag", TRUE, weekend, session)
      set_random_dish("Zaterdag", TRUE, weekend, session)
      set_random_dish("Zondag", preptime <= 120, doordeweeks, session)
    })
    observeEvent(input$sort_dishes, {
      sorted_dishes <- sort_dish_df(values$dishes, input$sort_dishes)
      rebuild_weekmenu_inputs(sorted_dishes)
    })
    observeEvent(values$dishes, {
      sorted_dishes <- sort_dish_df(values$dishes, input$sort_dishes %||% "Bereidingstijd")
      rebuild_weekmenu_inputs(sorted_dishes)
    })

    observeEvent(input$add_weekmenu_products_to_basket, {
      selected_dishes <- unlist(values$weekmenu)

      dish_ingredients <- values$dish_ingredients |>
        inner_join(values$dishes |> filter(name %in% selected_dishes),
                   by = "dish_id")
      dish_ingredients$name <- factor(dish_ingredients$name, levels = unique(selected_dishes), ordered = TRUE)
      dish_ingredients <- dish_ingredients |>
        mutate(current_sort = seq_len(NROW(dish_ingredients))) |>
        arrange(name, current_sort)

      missing_idx <- which(is.na(dish_ingredients$product_url) | dish_ingredients$quantity == 0)
      missing_n_dish <- length(unique(dish_ingredients$name[is.na(dish_ingredients$product_url) | dish_ingredients$quantity == 0]))
      missing_n_product <- length(unique(dish_ingredients$label[is.na(dish_ingredients$product_url) | dish_ingredients$quantity == 0]))

      # Store for later use by confirm handler
      values$pending_dish_ingredients <- dish_ingredients
      values$pending_missing_idx <- missing_idx

      if (length(missing_idx) == 0) {
        # No missing products, resume immediately
        ingredients <- rep(dish_ingredients$product_url, dish_ingredients$quantity)

        if (length(ingredients) == 0) {
          showNotification("Geen artikelen om toe te voegen.", type = "error")
        } else {
          add_to_basket(product_url = ingredients,
                        quantity = 1,
                        label = "Weekmenu")
        }

      } else {
        last_dish_name <- ""
        # Build modal with one selectise per NA
        ui_elems <- lapply(missing_idx, function(i) {
          current_label <- if (last_dish_name == dish_ingredients$name[i]) NULL else dish_ingredients$name[i]
          last_dish_name <<- dish_ingredients$name[i]
          if (dish_ingredients$quantity[i] == 0) {
            # optional ingredient - checkbox
            tagList(
              if (!is.null(current_label)) h5(current_label) else NULL,
              div(class = "optional-item",
                  checkboxInput(inputId = paste0("missing_product_", i),
                                label = get_product_name_unit(dish_ingredients$product_url[i]),
                                value = FALSE,
                                width = "100%")))
          } else {
            # flexibel ingredient - selectbox
            tagList(
              if (!is.null(current_label)) h5(current_label) else NULL,
              div(class = "flexible-item",
                  selectizeInput(inputId = paste0("missing_product_", i),
                             label = NULL,
                             choices = NULL,
                             width = "100%",
                             options = list(
                               placeholder = dish_ingredients$label[i],
                               maxOptions = 25,
                               dropdownParent = NULL,
                               onInitialize = I('function() { this.setValue(""); }'),
                               inputAttr = list(
                                 autocomplete = "off",
                                 autocorrect = "off",
                                 autocapitalize = "off",
                                 spellcheck = "false"
                               ),
                               render = I("{
                              option: function(item, escape) {
                                return '<div class=\"product-option\" style=\"display: flex; align-items: center; height: 50px;\">' +
                                         '<img src=\"' + escape(item.img) + '\" style=\"height: 40px; width: 40px; object-fit: contain; margin-right: 10px;\" />' +
                                         '<div style=\"flex: 1; min-width: 0;\">' +
                                           '<div style=\"font-weight: normal; text-align: left;\">' + escape(item.label) + '</div>' +
                                           '<div style=\"color: grey; font-size: 0.8em; text-align: left;\">' + escape(item.subtext) + '</div>' +
                                         '</div>' +
                                       '</div>';
                              },
                              item: function(item, escape) {
                                return '<div>' + escape(item.label) + '</div>';
                              }
                            }")))))
          }
        })
        showModal(modalDialog(
          title = "Flexibele en optionele ingredi\U00EBnten",
          tagList(
            p(HTML(paste0("Er ",
                          ifelse(missing_n_dish == 1,
                                 "is een gerecht ",
                                 paste0("zijn ", missing_n_dish, " gerechten ")),
                          "met ", ifelse(missing_n_product == 1, "een ", ""),
                          "<span class='text-primary'>flexibel", ifelse(missing_n_product == 1, "", "e"), "</span> en/of ",
                          "<span class='text-secondary'>optione", ifelse(missing_n_product == 1, "el", "le"), "</span>",
                          " ingredi\U00EBnt", ifelse(missing_n_product == 1, "", "en"),
                          ". Vul deze hieronder in, of laat leeg om niets toe te voegen."))),
            br(),
            ui_elems
          ),
          easyClose = FALSE,
          footer = tagList(
            modalButton("Annuleren"),
            actionButton("confirm_missing_products", "Verder")
          )
        ))

        # Populate all selectises with the large remote list
        for (i in missing_idx) {
          session$sendCustomMessage("updateSelectizeProductList", list(
            inputId = paste0("missing_product_", i),
            choices = shinyplus_env$product_choices
          ))
        }
      }
    })
    observeEvent(input$confirm_missing_products, {
      req(values$pending_dish_ingredients)
      req(values$pending_missing_idx)

      dish_ingredients <- values$pending_dish_ingredients
      missing_idx <- values$pending_missing_idx

      # Retrieve each selected product
      for (i in missing_idx) {
        chosen <- input[[paste0("missing_product_", i)]]
        if (dish_ingredients$quantity[i] == 0 && isTRUE(chosen)) {
          # optional ingredient
          dish_ingredients$quantity[i] <- 1
        } else if (!is.null(chosen) && nzchar(chosen)) {
          # flexibel ingredient
          dish_ingredients$product_url[i] <- chosen
        }
      }

      removeModal()
      dish_ingredients <- dish_ingredients |> filter(!is.na(product_url))

      # Continue with your original behaviour
      ingredients <- rep(dish_ingredients$product_url, dish_ingredients$quantity)

      if (length(ingredients) == 0) {
        showNotification("Geen artikelen om toe te voegen.", type = "error")
      } else {
        add_to_basket(product_url = ingredients,
                      quantity = 1,
                      label = "Weekmenu")
      }

      # Clean up
      values$pending_dish_ingredients <- NULL
      values$pending_missing_idx <- NULL
    })


    observeEvent(input$weekmenu_clear, {
      lapply(weekdays_list_full, function(day) {
        updateSelectizeInput(
          session,
          inputId = paste0("dish_day_", day),
          selected = ""
        )
      })
    })

    observeEvent(input$ics_weekmenu, {
      selected_dishes <- unlist(values$weekmenu)
      selected_dishes <- selected_dishes[names(selected_dishes) %in% weekdays_list]
      if (all(selected_dishes == "")) {
        showNotification("Geen gerechten geselecteerd.", type = "message")
        return(invisible())
      }

      weekmenu <- tibble(day = weekdays_list,
                         name = selected_dishes) |>
        left_join(values$dishes, by = "name")

      ingredients <- values$dish_ingredients |>
        filter(dish_id %in% weekmenu$dish_id, !is.na(product_url)) |>
        group_by(dish_id) |>
        summarise(ingredients = paste("*", get_product_name_unit(product_url), collapse = "\n"))

      first_monday <- Sys.Date() + (1 - as.integer(format(Sys.Date(), "%u"))) %% 7
      weekmenu <- weekmenu |>
        left_join(ingredients, by = "dish_id") |>
        mutate(date = first_monday + c(0:6),
               start_time = as.POSIXct(paste(date, "17:30")),
               end_time = as.POSIXct(paste(date, "18:30")),
               summary = paste("Eten:", name),
               description = ifelse(trimws(instructions) %in% c("", NA),
                                    "",
                                    paste0("Instructies:\n\n",
                                           map_chr(instructions, ~markdown_text(.x)))),
               description = ifelse(ingredients %in% c("", NA),
                                    description,
                                    paste0(description, "\n\nIngredi\U00EBnten om te gebruiken:\n\n",
                                           map_chr(ingredients, ~markdown_text(.x))))) |>
        filter(name != "")
      out <- tibble()

      for (i in seq_len(nrow(weekmenu))) {
        event <- ic_event(start_time = weekmenu$start_time[i],
                          end_time = weekmenu$end_time[i],
                          summary = weekmenu$summary[i],
                          event_properties = c(DESCRIPTION = gsub("\n", "\\n", weekmenu$description[i], fixed = TRUE),
                                               SEQUENCE = "0"),
                          more_properties = TRUE)
        out <- bind_rows(out, event)
      }

      tryCatch({
        out |>
          ical(ic_attributes = c(ic_attributes_vec(),
                                 NAME = "Weekmenu",
                                 DESCRIPTION = "Weekmenu",
                                 "X-WR-CALNAME" = "Weekmenu")) |>
          ic_write(file = ics_file())
        showNotification("PLUS Weekmenu in agenda opgeslagen.", type = "message")
      }, error = function(e) showNotification(paste0("Fout bij opslaan: ", conditionMessage(e)), type = "error"))
    })

    observeEvent(input$email_weekmenu, {
      selected_dishes <- unlist(values$weekmenu)
      selected_dishes <- selected_dishes[names(selected_dishes) %in% weekdays_list]
      if (all(selected_dishes == "")) {
        showNotification("Geen gerechten geselecteerd.", type = "message")
        return(invisible())
      }

      weekmenu <- tibble(day = weekdays_list,
                         name = selected_dishes) |>
        left_join(values$dishes, by = "name") |>
        left_join(values$dish_ingredients |> filter(!is.na(product_url)), by = "dish_id") |>
        filter(!is.na(day) & name != "") |>
        mutate(product_name = get_product_name_unit(product_url),
               day = factor(day, levels = weekdays_list_full, ordered = TRUE)) |>
        arrange(day)

      tryCatch({
        send_email_weekmenu(weekmenu)
        showNotification("PLUS Weekmenu per mail verzonden.", type = "message")
      }, error = function(e) showNotification(paste0("Fout bij verzenden: ", conditionMessage(e)), type = "error"))
    })

    ## 2. Aanbiedingen ----
    output$sale_header_ui <- renderUI({
      if (is.null(values$sale_items)) {
        tagList(
          div(id = "div_sale_retrieve",
              actionButton("sale_retrieve", "Aanbiedingen ophalen van PLUS.nl", icon = icon("cloud-arrow-down"), width = "100%"),
              br(),
              br()),
          p("Dit haalt de aanbiedingen op van ", a(href = plus_url("aanbiedingen"), "www.plus.nl/aanbiedingen", .noWS = "outside"), ".")
        )
      } else {
        df <- values$sale_items

        tagList(
          h5(paste0("Geldig van ", trimws(tolower(attributes(df)$promo_period)), ".")),
          p(paste("Er zijn", NROW(df), "aanbiedingen. Klik op een afbeelding om naar de aanbieding te gaan.")),
          br(),
          actionButton("add_sale_to_basket", "Toevoegen aan mandje", icon = icon("basket-shopping"), width = "100%"),
        )
      }
    })
    output$sale_items_ui <- renderUI({
      if (!is.null(values$sale_items)) {
        df <- values$sale_items
        groups <- unique(df$group)

        tagList(
          lapply(groups, function(grp) {
            group_df <- df[df$group == grp, ]

            if (nrow(group_df) == 1 && group_df$single_label == TRUE) {
              div(class = "sale-single-label",
                  a(href = plus_url(group_df$url), target = "_blank",
                    group_df$group))
            } else {
              tagList(
                h3(grp, class = "sale-group-title"),
                div(class = "sale-rows",
                    lapply(seq(1, nrow(group_df), by = 3), function(i) {
                      fluidRow(
                        lapply(i:min(i + 2, NROW(group_df)), function(j) {
                          row <- group_df[j, ]
                          column(
                            width = 4,
                            div(class = "sale-card",
                                a(href = plus_url(row$url), target = "_blank",
                                  img(src = row$img, class = "sale-img hover-preview")
                                ),
                                div(class = "sale-txt", row$sale_txt),
                                div(class = "sale-name", row$name),
                                div(class = "sale-unit", row$unit),
                                div(class = "price-line",
                                    span(class = "price-current", as_euro(row$price_current)),
                                    span(class = "price-previous", row$price_previous)
                                ),
                                if (isTRUE(row$is_product)) {
                                  div(class = "sale-qty",
                                      numericInput(
                                        inputId = paste0("qty_sale_", make.names(row$url)),
                                        label = NULL,
                                        value = 0,
                                        min = 0,
                                        step = 1,
                                        width = "100%"
                                      )
                                  )
                                }
                            )
                          )
                        })
                      )
                    })
                )
              )
            }
          })
        )
      }
    })
    observeEvent(input$sale_retrieve, {
      hide("div_sale_retrieve")
      show("loading_spinner")
      backup_product_list()
      df <- get_sales()  # this might take up to 5 seconds
      values$sale_items <- df
      hide("loading_spinner")
      show("sale-list")
      # update product lists
      product_list_last_updated(Sys.time())
    })
    observeEvent(input$add_sale_to_basket, {
      df <- values$sale_items
      qtys <- lapply(seq_len(nrow(df)), function(i) {
        row <- df[i, ]
        if (!isTRUE(row$is_product)) return(NULL)
        input_id <- paste0("qty_sale_", make.names(row$url))
        qty <- input[[input_id]]
        if (is.null(qty) || qty <= 0) return(NULL)
        tibble(product_url = row$url, quantity = qty)
      })
      qtys <- bind_rows(qtys)
      if (nrow(qtys) == 0) {
        showNotification("Geen artikelen om toe te voegen.", type = "error")
      } else {
        add_to_basket(product_url = qtys$product_url, quantity = qtys$quantity, label = "Aanbieding")
      }
    })

    ## 3. Vast ----

    fixed_settings_expanded <- reactiveVal(FALSE)

    observeEvent(input$fixed_settings_open, {
      fixed_settings_expanded(TRUE)
      show("add_fixed_product")
    })
    observeEvent(input$fixed_items_ui_content, {
      if (is.null(input$fixed_items_ui_content)) return()
      html <- read_html(input$fixed_items_ui_content)
      rows <- html_elements(html, ".products-list-row")
      new_order <- character(length(rows))
      for (i in seq_along(rows)) {
        row <- rows[[i]]
        a_tag <- html_element(row, "a[href]")
        if (!is.na(a_tag)) {
          # it's a product row; extract href
          new_order[i] <- html_attr(a_tag, "href")
        } else {
          h6_tag <- html_element(row, "h6")
          if (!is.na(h6_tag)) {
            # it's a heading row; extract text
            new_order[i] <- html_text2(h6_tag)
          } else {
            # fallback
            new_order[i] <- NA_character_
          }
        }
      }
      # remove NAs, if any
      new_order <- new_order[!is.na(new_order)]
      # remove plus.nl prefix
      new_order <- gsub("https://www.plus.nl", "", new_order, fixed = TRUE)
      # set new values - will be saved automatically
      values$fixed_products <- new_order
    })
    observeEvent(input$fixed_settings_close, {
      # save contents to input$fixed_items_ui_content to update `values$fixed_products`
      session$sendCustomMessage("get_element_content", "fixed_items_ui")
      fixed_settings_expanded(FALSE)
      hide("add_fixed_product")
    })

    output$fixed_settings_ui <- renderUI({
      if (fixed_settings_expanded() == FALSE) {
        actionButton("fixed_settings_open", "Bewerken", icon = icon("pen-to-square"), width = "100%")
      } else {
        tagList(
          actionButton("add_fixed_product_button", "Naar vaste artikelen", icon = icon("plus"), width = "100%"),
          br(),
          br(),
          fluidRow(
            h6("Tussenkopje toevoegen"),
            column(7, textInput("text_fixed_heading", NULL, placeholder = "(Naam van tussenkopje)", width = "100%")),
            column(5, actionButton("add_fixed_heading", "Toevoegen", icon = icon("plus"), width = "100%"))
          ),
          actionButton("fixed_settings_close", "Bewerkingen sluiten", icon = icon("caret-up"), width = "100%"),
          div(class = "div-fixed-expanded"),
        )
      }
    })

    # save to fixed product RDS if anything is changed
    observeEvent(values$fixed_products, {
      req(selected_email())
      saveRDS(values$fixed_products, fixed_products_file())
    }, ignoreInit = TRUE)

    output$fixed_items_ui <- renderUI({
      if (length(values$fixed_products) == 0) return(p("Nog geen vaste artikelen."))

      sale_items <- values$sale_items

      rows <- lapply(values$fixed_products, function(prod) {
        row_id <- paste0("fixed_item_", make.names(prod))
        is_product <- grepl("/product/", prod)

        if (!is_product) {
          # Heading rows
          if (isFALSE(fixed_settings_expanded())) {
            fluidRow(
              id = row_id,
              class = "row products-list-row fixed-heading-collapsed",
              column(
                12, class = "fixed-heading",
                # tags$span(class = "drag-handle", icon("bars")),
                h6(prod)
              )
            )
          } else {
            fluidRow(
              id = row_id,
              class = "row products-list-row",
              column(
                10, class = "fixed-heading",
                h6(prod)
              ),
              column(
                1, class = "product-list-col3 fixed_trash_icon",
                actionButton(
                  paste0("fixed_remove_heading_", make.names(prod)),
                  label = NULL, icon = icon("trash"),
                  class = "btn-danger btn-sm", style = "margin-top: -8px;"
                )
              ),
              column(
                1, class = "product-list-col4",
                tags$span(class = "drag-handle", icon("bars"))
              )
            )
          }
        } else {
          # Product rows
          if (isFALSE(fixed_settings_expanded())) {
            fluidRow(
              id = row_id,
              class = "row products-list-row",
              column(
                2, class = "product-list-col1",
                # tags$span(class = "drag-handle", icon("bars")),
                div(class = "products-list-img", height = "100%",
                    a(href = plus_url(prod), target = "_blank",
                      img(src = get_product_image(prod), width = "100%", class = "hover-preview")
                    )
                )
              ),
              column(
                8, class = "product-list-col2",
                if (prod %in% sale_items$url) {
                  div(class = "products-list-p", height = "100%",
                      p(class = "text-danger", HTML(paste0(
                        get_product_name(prod),
                        span(class = "basket-label sale", "aanbieding"), " ",
                        span(class = "product-qty", paste0(symbol$bullet, " ", get_product_unit(prod))),
                        if (sale_items$sale_txt[match(prod, sale_items$url)] != "")
                          span(class = "product-qty", paste0(" ", symbol$bullet, " ", sale_items$sale_txt[match(prod, sale_items$url)])),
                        span(class = "product-qty", paste0(" ", symbol$bullet, " \U20ac ", sale_items$price_current[match(prod, sale_items$url)], " ")),
                        if (sale_items$price_previous[match(prod, sale_items$url)] != "")
                          span(class = "price-previous", paste0(" \U20ac ", sale_items$price_previous[match(prod, sale_items$url)]))
                      )))
                  )
                } else {
                  div(class = "products-list-p", height = "100%",
                      p(HTML(paste0(
                        get_product_name(prod), " ",
                        span(class = "product-qty", paste0(symbol$bullet, " ", get_product_unit(prod)))
                      )))
                  )
                }
              ),
              column(
                2, class = "product-list-col3",
                div(class = "products-list-qty", height = "100%",
                    numericInput(paste0("qty_fixed_", make.names(prod)), NULL, value = 0, min = 0, step = 1, width = "100%")
                )
              )
            )
          } else {
            fluidRow(
              id = row_id,
              class = "row products-list-row",
              column(
                2, class = "product-list-col1",
                div(class = "products-list-img", height = "100%",
                    a(href = plus_url(prod), target = "_blank",
                      img(src = get_product_image(prod), width = "100%", class = "hover-preview")
                    )
                )
              ),
              column(
                8, class = "product-list-col2",
                if (prod %in% sale_items$url) {
                  div(class = "products-list-p", height = "100%",
                      p(class = "text-danger", HTML(paste0(
                        get_product_name(prod), " ",
                        span(class = "product-qty", paste0(symbol$bullet, " ", get_product_unit(prod)))
                      )))
                  )
                } else {
                  div(class = "products-list-p", height = "100%",
                      p(HTML(paste0(
                        get_product_name(prod), " ",
                        span(class = "product-qty", paste0(symbol$bullet, " ", get_product_unit(prod)))
                      )))
                  )
                }
              ),
              column(
                1, class = "product-list-col3 fixed_trash_icon",
                actionButton(paste0("remove_fixed_", make.names(prod)), "", icon = icon("trash"), class = "btn-danger btn-sm")
              ),
              column(
                1, class = "product-list-col4",
                tags$span(class = "drag-handle", icon("bars"))
              )
            )
          }
        }
      })

      tagList(
        # minimal, non-intrusive handle/ghost styling
        tags$style(HTML("
      .drag-handle { cursor: move; display: inline-block; color: #888; }
      .sortable-ghost { opacity: 0.4; }
      .sortable-chosen { background: rgba(0,0,0,0.03); }
    ")),
        # container that holds the rows
        div(id = "fixed_items_container", rows),
        # activate SortableJS on the container
        sortable_js(
          css_id = "fixed_items_container",
          options = sortable_options(
            handle = ".drag-handle",
            animation = 150,
          )
        )
      )
    })

    # Manage fixed_products (add/remove)
    observeEvent(input$add_fixed_product_button, {
      req(input$add_fixed_product)
      prod <- input$add_fixed_product
      if (!is.null(prod) && !(prod %in% values$fixed_products)) {
        values$fixed_products <- unique(c(values$fixed_products, prod))
      }
      updateSelectInput(session, "add_fixed_product", selected = "")
    })

    observeEvent(input$add_fixed_heading, {
      req(input$text_fixed_heading)
      prod <- input$text_fixed_heading
      if (!is.null(prod) && !(prod %in% values$fixed_products)) {
        values$fixed_products <- unique(c(values$fixed_products, prod))
      }
      updateTextInput(session, "text_fixed_heading", value = "")
    })

    observe({
      req(length(values$fixed_products) > 0)
      shinyplus_env$fixed_item_moved <- FALSE
      lapply(values$fixed_products, function(prod) {
        # trash icon for headings
        observeEvent(input[[paste0("fixed_remove_heading_", make.names(prod))]], {
          values$fixed_products <- values$fixed_products[values$fixed_products != prod]
          shinyplus_env$fixed_item_moved <- TRUE
        }, ignoreInit = TRUE)
        # trash icon for products
        observeEvent(input[[paste0("remove_fixed_", make.names(prod))]], {
          values$fixed_products <- values$fixed_products[values$fixed_products != prod]
          shinyplus_env$fixed_item_moved <- TRUE
        }, ignoreInit = TRUE)
      })
    })


    # Add selected fixed items + quantities to planning basket
    observeEvent(input$add_fixed_to_basket, {
      qtys <- lapply(values$fixed_products, function(prod) {
        qty <- input[[paste0("qty_fixed_", make.names(prod))]]
        if (is.null(qty) || qty <= 0) return(NULL)
        tibble(product_url = prod, quantity = qty)
      })

      qtys <- bind_rows(qtys)
      if (nrow(qtys) == 0) {
        showNotification("Geen artikelen om toe te voegen.", type = "error")
      } else {
        add_to_basket(product_url = qtys$product_url, quantity = qtys$quantity, label = "Vast")
      }
    })

    observeEvent(input$fixed_to_zero, {
      for (prod in values$fixed_products) {
        input_id <- paste0("qty_fixed_", make.names(prod))
        updateNumericInput(session, inputId = input_id, value = 0)
      }
    })


    ## 4. Mandje ----

    # save to basket RDS if anything is changed
    observeEvent(values$basket, {
      req(selected_email())
      values$basket <- values$basket |> filter(quantity > 0)
      saveRDS(values$basket, basket_file())
      # update number on basket icon
      session$sendCustomMessage("updateBasketCount", sum(values$basket$quantity, na.rm = TRUE))
    }, ignoreInit = TRUE)

    # basket overview table
    output$basket_overview_table <- renderUI({
      if (nrow(values$basket) == 0) return(h4("Mandje is leeg."))

      tagList(
        p(HTML(paste0("<strong>Totaal artikelen:</strong> ", sum(values$basket$quantity, na.rm = TRUE), " (uniek: ", nrow(values$basket), ")"))),
        br(),
        br(),
        lapply(seq_len(nrow(values$basket)), function(i) {
          row <- values$basket[i, ]
          prod <- row$product_url
          qty <- row$quantity
          src <- row$label
          src_label <- tolower(row$label)
          if (src_label == "aanbieding") src_label <- "sale"
          if (src_label == "vast") src_label <- "fixed"
          input_id <- paste0("basket_qty_", make.names(prod))
          remove_id <- paste0("basket_remove_", make.names(prod))

          fluidRow(
            class = "row products-list-row",
            column(2, class = "product-list-col1", div(class = "products-list-img", a(href = plus_url(prod), target = "_blank", img(src = get_product_image(prod), width = "100%", class = "hover-preview")))),
            column(6, class = "product-list-col2", div(class = "products-list-p", p(HTML(paste0(get_product_name(prod), " ",
                                                                   span(class = "product-qty", paste0(symbol$bullet, " ", get_product_unit(prod), " ", symbol$bullet)),
                                                                   "<span class='basket-label ", src_label, "'>", src, "</span>"))))),
            column(2, class = "product-list-col3", div(class = "products-list-qty", numericInput(input_id, NULL, value = qty, min = 1, step = 1, width = "100%"))),
            column(2, class = "product-list-col4", actionButton(remove_id, "", icon = icon("trash"), class = "btn-danger btn-sm", style = "margin-top: -8px;"))
          )
        })
      )
    })

    # Make quantity and remove buttons work
    observe({
      req(nrow(values$basket) > 0)
      lapply(values$basket$product_url, function(prod) {
        input_id <- paste0("basket_qty_", make.names(prod))
        observeEvent(input[[input_id]], {
          new_qty <- input[[input_id]]
          values$basket <- values$basket |>
            mutate(quantity = if_else(as.character(product_url) == as.character(prod), new_qty, quantity))
        }, ignoreInit = TRUE)
      })
    })
    observe({
      req(nrow(values$basket) > 0)
      lapply(values$basket$product_url, function(prod) {
        observeEvent(input[[paste0("basket_remove_", make.names(prod))]], {
          values$basket <- values$basket |> filter(as.character(product_url) != as.character(prod))
        }, ignoreInit = TRUE)
      })
    })


    observeEvent(input$text_basket, {
      # Escape HTML special characters, ensure plain text
      text <- get_product_name_unit(values$basket$product_url)
      text[values$basket$quantity > 1] <- paste0(values$basket$quantity[values$basket$quantity > 1], "x ", text[values$basket$quantity > 1])
      text <- gsub("<", "&lt;", text)
      text <- gsub(">", "&gt;", text)
      text <- c("BOODSCHAPPEN:", "", text)
      text <- paste0(text, collapse = "<br>")

      # Send to browser
      session$sendCustomMessage("openPlainTextTab", text)
    })

    observeEvent(input$add_extra_product, {
      req(input$add_extra_product)
      product_url <- input$add_extra_product

      add_to_basket(product_url = product_url, quantity = 1, label = "Extra", on_top = TRUE)
      updateSelectInput(session, "add_extra_product", selected = "")
    })

    # Sorting buttons
    observeEvent(input$sort_basket_name, {
      req(nrow(values$basket) > 0)
      current <- values$basket
      # sort ascending
      values$basket <- values$basket |>
        left_join(shinyplus_env$product_list |> select(url, name),
                  by = c("product_url" = "url")) |>
        arrange(name) |>
        select(-name)
      if (identical(current, values$basket)) {
        # sort descending
        values$basket <- values$basket |>
          left_join(shinyplus_env$product_list |> select(url, name),
                    by = c("product_url" = "url")) |>
          arrange(desc(name)) |>
          select(-name)
      }
    })
    observeEvent(input$sort_basket_label, {
      req(nrow(values$basket) > 0)
      current <- values$basket

      base_levels <- c("Weekmenu", "Aanbieding", "Vast", "Extra")
      other_levels <- setdiff(sort(unique(values$basket$label)), base_levels)
      all_levels <- c(base_levels, other_levels)

      # sort ascending
      values$basket <- values$basket |>
        mutate(label = factor(label, levels = all_levels, ordered = TRUE)) |>
        arrange(label) |>
        mutate(label = as.character(label))
      if (identical(current, values$basket)) {
        # sort descending
        values$basket <- values$basket |>
          mutate(label = factor(label, levels = all_levels, ordered = TRUE)) |>
          arrange(desc(label)) |>
          mutate(label = as.character(label))
      }
    })
    observeEvent(input$sort_basket_quantity, {
      req(nrow(values$basket) > 0)
      current <- values$basket

      # sort descending
      values$basket <- values$basket |> arrange(desc(quantity))
      if (identical(current, values$basket)) {
        # sort ascending
        values$basket <- values$basket |> arrange(quantity)
      }
    })

    observeEvent(input$email_basket, {
      tryCatch({
        send_email_basket(values$basket)
        showNotification("Mandje per mail verzonden.", type = "message")
      }, error = function(e) showNotification(paste0("Fout bij verzenden: ", conditionMessage(e)), type = "error"))
    })

    # Send basket to cart
    observeEvent(input$send_basket_to_cart, {
      if (!values$logged_in) {
        showNotification("Log eerst in om te verzenden naar PLUS Winkelwagen.", type = "error")
        return()
      }

      req(nrow(values$basket) > 0)

      showModal(modalDialog(
        title = HTML(paste0("In ", plus_cart_text(), " plaatsen")),
        p(HTML(paste0("Weet je zeker dat je ",
                ifelse(NROW(values$basket) == 1,
                       "dit artikel",
                       paste("deze", NROW(values$basket), "artikelen")),
                " in de ", plus_cart_text(), " wilt plaatsen? Dit kan even duren."))),
        footer = tagList(
          modalButton("Annuleren"),
          actionButton("confirm_send_basket", "OK", class = "btn-primary")
        )
      ))
    })

    observeEvent(input$confirm_send_basket, {
      removeModal()

      showModal(modalDialog(
        title = HTML(paste0("In ", plus_cart_text(), " plaatsen...")),
        tagList(
          div(
            class = "progress",
            div(
              id = "progress_bar",
              class = "progress-bar progress-bar-striped progress-bar-animated",
              role = "progressbar",
              style = "width: 0%; background-color: rgb(85, 77, 167);",
              "0%"
            )
          ),
          br(),
          div(id = "progress_name", style = "text-align:center; font-weight:bold;")
        ),
        footer = NULL,
        easyClose = FALSE
      ))

      n <- nrow(values$basket)
      succesful_urls <- character(0)

      for (i in seq_len(n)) {
        url <- as.character(values$basket$product_url[i]) # was a factor
        quantity <- values$basket$quantity[i]
        name <- escape_js_string(get_product_name_unit(url))
        name_qty <- paste0(name, " x", quantity)
        pct <- round(i / n * 100)

        runjs(sprintf("
          $('#progress_bar').css({
            'width': '%d%%',
            'background-color': 'rgb(85, 77, 167)'
          });
          $('#progress_bar').text('%d%%');
          $('#progress_name').html('%s');
        ", pct, pct, name_qty))

        successfully_added <- tryCatch(plus_add_products(url, quantity = quantity, email = shinyplus_env$current_user_email, password = shinyplus_env$current_user_password, info = FALSE),
                                       error = function(e) 0)
        if (input$remove_cart_from_basket == TRUE && successfully_added > 0) {
          # remove product from local basket
          values$basket$quantity[i] <- values$basket$quantity[i] - successfully_added
        } else if (successfully_added == 0) {
          showNotification(session = session, paste0("Artikel '", get_product_name_unit(url), "' kon niet toegevoegd worden."), type = "error", duration = NULL)
        }
      }

      removeModal()
      showNotification("Gereed.", type = "message")

      # Refresh cart summary + table
      values$online_cart <- plus_current_cart(email = shinyplus_env$current_user_email, password = shinyplus_env$current_user_password, info = FALSE)
      if (is.null(values$online_cart)) {
        showNotification("PLUS Winkelwagen niet up-to-date, vernieuwen...", type = "message")
        Sys.sleep(2)
        values$online_cart <- plus_current_cart(email = shinyplus_env$current_user_email, password = shinyplus_env$current_user_password, info = FALSE)
      }
    })

    observeEvent(input$clear_basket, {
      if (NROW(values$basket) == 0) {
        showNotification("Mandje is leeg.", type = "message")
        return()
      }
      showModal(modalDialog(
        title = "Weet je het zeker?",
        "Hiermee wordt het mandje leeggemaakt. Dit kan niet ongedaan gemaakt worden.",
        easyClose = FALSE,
        footer = tagList(
          modalButton("Annuleren"),
          actionButton("confirm_clear_basket", "Leegmaken", class = "btn-danger")
        )
      ))
    })
    observeEvent(input$confirm_clear_basket, {
      values$basket <- values$basket |> slice(0)
      removeModal()
    })

    observeEvent(input$clean_basket, {
      if (!values$logged_in) {
        showNotification("Log eerst in om mandje op te kunnen schonen.", type = "error")
        return()
      }
      if (NROW(values$basket) == 0) {
        showNotification("Mandje is leeg.", type = "message")
        return()
      }
      if (NROW(values$online_cart) == 0) {
        showNotification("PLUS Winkelwagen is leeg, niets om op te schonen.", type = "message")
        return()
      }
      showModal(modalDialog(
        title = "Weet je het zeker?",
        HTML(paste0("Hiermee worden artikelen uit het mandje verwijderd die al in de ", plus_cart_text(), " staan.")),
        easyClose = FALSE,
        footer = tagList(
          modalButton("Annuleren"),
          actionButton("confirm_clean_basket", "Opschonen", class = "btn-primary")
        )
      ))
    })
    observeEvent(input$confirm_clean_basket, {
      cart <- values$online_cart |>
        # join to get product urls
        left_join(shinyplus_env$product_list, by = c("product" = "name", "unit"))
      n_basket <- sum(values$basket$quantity, na.rm = TRUE)
      for (i in seq_len(NROW(cart))) {
        if (cart$url[i] %in% values$basket$product_url) {
          # substract quantity by the quantity in the PLUS cart
          # a resulting quantity if 0 will be removed from the basket automatically
          values$basket <- values$basket |>
            mutate(quantity = ifelse(product_url == cart$url[i] & quantity > 0, quantity - cart$quantity[i], quantity))
        }
      }
      removeModal()
      showNotification(paste0(n_basket - sum(values$basket$quantity, na.rm = TRUE), " artikelen uit mandje verwijderd."), type = "message")
    })


    # Server: PLUS Cart ----

    output$online_cart_summary <- renderUI({
      if (!values$logged_in) {
        return(
          p(HTML(paste0("Om artikelen in de online ", plus_cart_text(FALSE), " te zien, log eerst in via het menu 'Inloggen'.")))
        )
      }

      if (is.null(values$online_cart)) {
        return(tagList(
          p(HTML(paste0("Klik op de knop om de ", plus_cart_text(), " te vernieuwen."))),
          actionButton("refresh_online_cart", "Vernieuwen", icon = icon("refresh")),
        ))
      } else if (nrow(values$online_cart) == 0 && inherits(values$online_cart, "plus_cart")) {
        return(tagList(
          p(HTML(paste0("Geen artikelen; de ", plus_cart_text(), " is leeg."))),
          actionButton("refresh_online_cart", "Vernieuwen", icon = icon("refresh")),
        ))
      }

      total_items <- sum(values$online_cart$quantity, na.rm = TRUE)
      unique_items <- nrow(values$online_cart)
      original_total <- sum(values$online_cart$price_total, na.rm = TRUE)
      actual_total <- attributes(values$online_cart)$final_total
      saving_pct <- round(((original_total - actual_total) / original_total) * 100, 1)

      tagList(
        p("De inhoud van deze winkelwagen is opgehaald van de ",
          a(href = plus_url("winkelwagen"),
            target= "_blank",
            "online PLUS Winkelwagen", .noWS = "outside"),
          ". Wijzigingen kunnen alleen daar worden aangebracht."),
        if (original_total - actual_total < 0) p(HTML(paste0("Een negatieve korting kan voorkomen als er bijv. statiegeld gerekend wordt. De doorgehaalde prijs is dan de som van alle prijzen uit de ", plus_cart_text(), ", terwijl de totale prijs hoger is (in dit geval ", as_euro(actual_total - original_total), " hoger)."))),
        br(),
        h4(HTML(paste0("<strong>Totale prijs:</strong> ",
                       as_euro(sum(actual_total, na.rm = TRUE)),
                       ifelse(original_total != actual_total,
                              paste0(" <span class='price-previous'>", as_euro(original_total), "</span>"),
                              "")))),
        p(HTML(paste0("<strong>Korting:</strong> ", as_euro(original_total - actual_total), " (", format(saving_pct, nsmall = 1, big.interval = ".", decimal.mark = ","), "%)"))),
        p(HTML(paste0("<strong>Totaal artikelen:</strong> ", total_items, " (uniek: ", unique_items, ")"))),
        br(),
        fluidRow(
          column(4, actionButton("checkout", "Afrekenen bij PLUS.nl", class = "btn-success", icon = icon("cash-register"), width = "100%")),
          column(5, actionButton("view_cart", "Op PLUS.nl bekijken", icon = icon("cart-shopping"), width = "100%")),
          column(3, actionButton("refresh_online_cart", "Vernieuwen", icon = icon("refresh"), width = "100%")),
        )
      )
    })
    output$online_cart_table <- renderDT({
      req(values$logged_in)
      req(values$online_cart)

      if (NROW(values$online_cart) == 0) {
        return(datatable(
          data.frame(),
          rownames = FALSE,
          selection = "none",
          options = list(
            dom = "t",
            stripeClasses = NULL # remove row striping
          )
        ))
      }

      cart <- values$online_cart |>
        arrange(product) |>
        left_join(shinyplus_env$product_list, by = c("product" = "name", "unit")) |>
        mutate(img = if_else(is.na(img), img,
                             paste0(
                               "<div style='height: 70px; max-width: 100px;'>",
                               "<img src='", img, "' style='max-height: 70px; max-width: 100px; margin-left: auto; margin-right: auto;'>",
                               "</div>")),
               url = if_else(is.na(url), url,
                             paste0("<a href='https://www.plus.nl", url, "' target='_blank'>",
                                    "<i class='fas fa-right-from-bracket'></i></a>")),
               name_unit = paste0(product, " (", unit, ")")) |>
        as_tibble()


      display_cart <- cart |>
        select(" " = img,
               Artikel = name_unit,
               Prijs = price,
               "Per kg|L|st" = per_kg_l_st,
               Aantal = quantity,
               Totaal = price_total,
               Artikelinfo = url)

      datatable(
        display_cart,
        escape = FALSE, # allow HTML for image and icon
        rownames = FALSE,
        selection = "none",
        options = list(
          dom = "t",
          paging = FALSE,
          columnDefs = list(
            list(className = "dt-center", targets = 0),
            list(className = "dt-left", targets = 1),
            list(className = "dt-center", targets = 2:6)
          ),
          stripeClasses = NULL # remove row striping
        )
      ) |>
        formatCurrency(columns = c("Prijs", "Per kg|L|st", "Totaal"),
                       currency = "\U20ac ", mark = ".", dec.mark = ",", digits = 2)
    })

    observeEvent(input$checkout, {
      runjs(sprintf("window.open('%s', '_blank')", plus_url("checkout")))
    })
    observeEvent(input$view_cart, {
      runjs(sprintf("window.open('%s', '_blank')", plus_url("winkelwagen")))
    })

    observeEvent(input$refresh_online_cart, {
      req(values$logged_in)
      showNotification("PLUS Winkelwagen vernieuwen...", type = "message")
      values$online_cart <- plus_current_cart(email = shinyplus_env$current_user_email, password = shinyplus_env$current_user_password, info = FALSE)
      if (NROW(values$online_cart) == 0) {
        showNotification("Geen verbinding, opnieuw proberen...", type = "message")
        Sys.sleep(3)
        values$online_cart <- plus_current_cart(email = shinyplus_env$current_user_email, password = shinyplus_env$current_user_password, info = FALSE)
      }
    })


    # Server: Manage dishes ----

    # helper: generate unique dish_id
    generate_dish_id <- function() {
      if (nrow(values$dishes) == 0) return(1L)
      max(values$dishes$dish_id, na.rm = TRUE) + 1L
    }

    # update dish selector dropdown
    observe({
      current_id <- input$selected_dish
      choices <- values$dishes$dish_id |> stats::setNames(values$dishes$name)
      updateSelectInput(
        session,
        "selected_dish",
        choices = choices, # critical
        selected = if (current_id %in% values$dishes$dish_id) current_id else NULL
      )
    })

    # new dish = clear form
    observeEvent(input$new_dish, {
      if (input$new_dish_name == "") {
        showNotification("Vul naam van gerecht in.", type = "error")
        return(invisible())
      }
      new_id <- generate_dish_id()
      values$dishes <- bind_rows(values$dishes, tibble(
        dish_id = new_id,
        name = input$new_dish_name,
        days = "Doordeweeks,Weekend,Avondeten",
        preptime = NA_integer_,
        vegetables = NA_integer_,
        meat = NA_character_,
        instructions = ""
      )) |>
        arrange(name)
      updateTextInput(session, "new_dish_name", value = "")
      values$new_dish_name <- input$new_dish_name
      updateSelectInput(session, "selected_dish", selected = new_id)
      saveRDS(values$dishes, dishes_file())
    })
    observeEvent(values$new_dish_name, {
      # required to update the select list when clicking new_dish
      req(values$new_dish_name %in% values$dishes$name)
      updateSelectInput(session, "selected_dish", selected = max(values$dishes$dish_id))
      values$new_dish_name <- NULL  # reset
    })
    # updating existing fields
    observeEvent(input$dish_name, {
      req(input$dish_id)
      values$dishes <- values$dishes |>
        mutate(name = if_else(dish_id == input$dish_id, input$dish_name, name)) |>
        arrange(name)
      saveRDS(values$dishes, dishes_file())
    })
    observeEvent(input$dish_days, {
      req(input$dish_id)
      values$dishes <- values$dishes |>
        mutate(days = if_else(dish_id == input$dish_id, paste(input$dish_days, collapse = ","), days))
      saveRDS(values$dishes, dishes_file())
    })
    observeEvent(input$dish_preptime, {
      req(input$dish_id)
      values$dishes <- values$dishes |>
        mutate(preptime = if_else(dish_id == input$dish_id, if_else(input$dish_preptime == " ", NA_integer_, as.integer(input$dish_preptime)), preptime))
      saveRDS(values$dishes, dishes_file())
    })
    observeEvent(input$dish_vegetables, {
      req(input$dish_id)
      values$dishes <- values$dishes |>
        mutate(vegetables = if_else(dish_id == input$dish_id, if_else(input$dish_vegetables == " ", NA_integer_, as.integer(input$dish_vegetables)), vegetables))
      saveRDS(values$dishes, dishes_file())
    })
    observeEvent(input$dish_meat, {
      req(input$dish_id)
      values$dishes <- values$dishes |>
        mutate(meat = if_else(dish_id == input$dish_id, if_else(input$dish_meat == " ", NA_character_, input$dish_meat), meat))
      saveRDS(values$dishes, dishes_file())
    })

    # dish instructions
    dish_instruction_edit_mode <- reactiveVal(FALSE)

    output$dish_instructions_ui <- renderUI({
      req(input$dish_id)
      raw_txt <- values$dishes |>
        filter(dish_id == input$dish_id) |>
        pull(instructions)
      if (isTRUE(dish_instruction_edit_mode())) {
        # edit mode
        tagList(
          textAreaInput("dish_instructions", "Instructies:",
                        value = raw_txt,
                        width = "100%", height = "300px"),
          p("Dit veld ondersteunt markdown."),
          actionButton("dish_instructions_save", "Instructies opslaan", icon = icon("floppy-disk"), width = "100%"))
      } else if (raw_txt == "") {
        # no instructions yet, no edit mode
        actionButton("dish_instructions_edit", "Instructies toevoegen", icon = icon("plus"), width = "100%")
      } else {
        # these are the rendered instructions
        tagList(
          p("Instructies:", style = "margin-bottom: 0;"),
          div(class = "dish_instructions_text", style = "margin-bottom: 0;",
              HTML(markdown_html(raw_txt, extensions = TRUE, smart = TRUE))
          ),
          actionButton("dish_instructions_edit", "Instructies bewerken", icon = icon("pencil"), width = "100%"))
      }
    })

    observeEvent(input$dish_instructions_save, {
      req(input$dish_id)
      dish_instruction_edit_mode(FALSE)
      values$dishes <- values$dishes |>
        mutate(instructions = if_else(dish_id == input$dish_id, trimws(input$dish_instructions), instructions))
      saveRDS(values$dishes, dishes_file())
    })
    observeEvent(input$dish_instructions_edit, {
      dish_instruction_edit_mode(TRUE)
    })

    # select existing dish
    observeEvent(input$selected_dish, {
      sel <- values$dishes |> filter(dish_id == input$selected_dish)
      if (nrow(sel) != 1) return()
      updateNumericInput(session, "dish_id", value = input$selected_dish)
      updateTextInput(session, "dish_name", value = sel$name)
      updateCheckboxGroupInput(session, "dish_days", selected = unlist(strsplit(sel$days, ",")))
      updateRadioButtons(session, "dish_preptime", selected = ifelse(is.na(sel$preptime), " ", sel$preptime))
      updateRadioButtons(session, "dish_vegetables", selected = ifelse(is.na(sel$vegetables), " ", sel$vegetables))
      updateRadioButtons(session, "dish_meat", selected = ifelse(is.na(sel$meat), " ", sel$meat))
      dish_instruction_edit_mode(FALSE) # turn off edit mode for instructions
    })

    # delete dish
    observeEvent(input$delete_dish, {
      req(input$selected_dish)
      dish_name <- values$dishes$name[values$dishes$dish_id == input$selected_dish]
      if (dish_name %in% values$weekmenu) {
        showNotification("Gerecht kan niet verwijderd worden omdat het momenteel in het weekmenu staat.", type = "error")
        return(invisible())
      }

      showModal(modalDialog(
        title = "Weet je het zeker?",
        paste0("Gerecht '", dish_name, "' verwijderen?"),
        easyClose = FALSE,
        footer = tagList(
          modalButton("Annuleren"),
          actionButton("confirm_delete_dish", "Verwijderen", class = "btn-danger")
        )
      ))
    })
    observeEvent(input$confirm_delete_dish, {
      req(input$selected_dish)
      sel_id <- values$dishes |> filter(dish_id == input$selected_dish) |> pull(dish_id)
      values$dishes <- values$dishes |> filter(dish_id != input$selected_dish)
      values$dish_ingredients <- values$dish_ingredients |> filter(dish_id != sel_id)

      saveRDS(values$dishes, dishes_file())
      saveRDS(values$dish_ingredients, dish_ingredients_file())

      removeModal()
      updateSelectInput(session, "selected_dish", choices = values$dishes$name[order(tolower(values$dishes$name))], selected = "")
    })

    # save to dish ingredients RDS if anything is changed
    observeEvent(values$dish_ingredients, {
      req(selected_email())
      saveRDS(values$dish_ingredients, dish_ingredients_file())
    }, ignoreInit = TRUE)

    # add ingredient
    observeEvent(input$add_ingredient, {
      if (input$ingredient_url == "") {
        if (trimws(input$ingredient_flexible) == "") {
          # nothing selected
          return(invisible())
        }
        values$dish_ingredients <- values$dish_ingredients |>
          bind_rows(tibble(
            dish_id = as.numeric(input$selected_dish),
            product_url = NA_character_,
            quantity = 1,
            label = trimws(input$ingredient_flexible)))
      } else {
        # selected from list
        values$dish_ingredients <- values$dish_ingredients |>
          bind_rows(tibble(
            dish_id = as.numeric(input$selected_dish),
            product_url = input$ingredient_url,
            quantity = ifelse(input$ingredient_optional == TRUE, 0, input$ingredient_quantity),
            label = NA_character_)) |>
          group_by(dish_id, product_url, label) |>
          summarise(quantity = sum(quantity, na.rm = TRUE), .groups = "drop")
      }
      values$dish_ingredients <- values$dish_ingredients |>
        mutate(sortname = tolower(ifelse(is.na(label), get_product_name(product_url), label))) |>
        arrange(dish_id, sortname) |>
        select(-sortname)
      updateSelectInput(session, "ingredient_url", selected = "")
      updateNumericInput(session, "ingredient_quantity", value = 1)
      updateCheckboxInput(session, "ingredient_optional", value = FALSE)
      updateTextInput(session, "ingredient_flexible", value = "")
    })

    # render ingredient table with remove buttons
    output$dish_ingredients_table <- renderUI({
      req(input$selected_dish)
      df <- values$dish_ingredients |> filter(dish_id == input$selected_dish)

      if (nrow(df) == 0) return(p("Nog geen ingredi\U00EBnten toegevoegd."))

      tagList(
        lapply(seq_len(nrow(df)), function(i) {
          row <- df[i, ]
          remove_id <- paste0("remove_ingr_", row$dish_id, "_", make.names(paste(row$product_url, row$label)))
          make_optional_id <- paste0("make_optional_", row$dish_id, "_", make.names(paste(row$product_url, row$label)))

          if (row$quantity == 0) {
            # optional product (quantity = 0)
            fluidRow(
              class = "row products-list-row",
              column(2, class = "product-list-col1", div(class = "products-list-img", a(href = plus_url(row$product_url), target = "_blank", img(src = get_product_image(row$product_url), width = "100%", class = "hover-preview")))),
              column(9, class = "product-list-col2", div(class = "products-list-p", p(HTML(paste0(get_product_name(row$product_url), " ",
                                                                                                  span(class = "product-qty", paste0(symbol$bullet, " ", get_product_unit(row$product_url), " ", symbol$bullet), " "),
                                                                                                  span(class = "basket-label weekmenu", "optioneel")))))),
              column(1, class = "product-list-col3", actionButton(remove_id, "", icon = icon("trash"), class = "btn-danger btn-sm", style = "margin-top: -8px;"))
            )
          } else if (is.na(row$label)) {
            # normal product
            fluidRow(
              class = "row products-list-row",
              column(2, class = "product-list-col1", div(class = "products-list-img", a(href = plus_url(row$product_url), target = "_blank", img(src = get_product_image(row$product_url), width = "100%", class = "hover-preview")))),
              column(9, class = "product-list-col2", div(class = "products-list-p", p(HTML(paste0(ifelse(row$quantity != 1, paste0("<strong>", row$quantity, "x</strong> "), ""),
                                                                                                  get_product_name(row$product_url), " ",
                                                                                                  span(class = "product-qty", paste0(symbol$bullet, " ", get_product_unit(row$product_url))),
                                                                                                  actionButton(make_optional_id, "optioneel maken", class = "btn_make_optional")))))),
              column(1, class = "product-list-col3", actionButton(remove_id, "", icon = icon("trash"), class = "btn-danger btn-sm", style = "margin-top: -8px;"))
            )
          } else {
            # no product - it's a label
            fluidRow(
              class = "row products-list-row",
              column(2, class = "product-list-col1", div(class = "products-list-img", img(src = get_product_image(row$product_url), width = "100%", class = "hover-preview"))),
              column(9, class = "product-list-col2", div(class = "products-list-p", p(HTML(paste0(row$label, " ", span(class = "product-qty", symbol$bullet), " <span class='basket-label fixed'>flexibel</span>"))))),
              column(1, class = "product-list-col3", actionButton(remove_id, "", icon = icon("trash"), class = "btn-danger btn-sm", style = "margin-top: -8px;"))
            )
          }
        })
      )
    })

    # Make remove buttons work
    observe({
      req(NROW(values$dish_ingredients) > 0)
      lapply(seq_len(nrow(values$dish_ingredients)), function(i) {
        row <- values$dish_ingredients[i, ]
        remove_id <- paste0("remove_ingr_", row$dish_id, "_", make.names(paste(row$product_url, row$label)))
        observeEvent(input[[remove_id]], {
          values$dish_ingredients <- values$dish_ingredients |> filter(!(dish_id == input$selected_dish & paste(product_url, label) == paste(row$product_url, row$label)))
        }, ignoreInit = TRUE)
      })
    })
    # Make optional buttons work
    observe({
      req(NROW(values$dish_ingredients) > 0)
      lapply(seq_len(nrow(values$dish_ingredients)), function(i) {
        row <- values$dish_ingredients[i, ]
        make_optional_id <- paste0("make_optional_", row$dish_id, "_", make.names(paste(row$product_url, row$label)))
        observeEvent(input[[make_optional_id]], {
          values$dish_ingredients <- values$dish_ingredients |>
            mutate(quantity = ifelse(dish_id == input$selected_dish & paste(product_url, label) == paste(row$product_url, row$label),
                                     0,
                                     quantity))
        }, ignoreInit = TRUE)
      })
    })


    # Server: Add products -----
    output$product_search <- renderUI({
      p("Druk op de zoek- of importeerknop om te beginnen.")
    })

    observeEvent(input$product_search_btn, {
      req(input$product_search_txt)
      search_url <- paste0("https://www.plus.nl/zoekresultaten?SearchTerm=", utils::URLencode(input$product_search_txt, reserved = TRUE))
      showNotification("Zoekopdracht uitvoeren op PLUS.nl...", type = "message", duration = 2)
      retrieve_plus_data(search_url)
    })

    observeEvent(input$product_import_btn, {
      req(input$product_import_html)
      retrieve_plus_data(input$product_import_html)
    })

    retrieve_plus_data <- function(search_url) {
      new_items <- tryCatch(create_product_list_internal(search_url), error = function(e) NULL)
      if (is.null(new_items)) {
        showNotification("Fout bij ophalen van gegevens.", type = "error")
      } else if (NROW(new_items) == 0) {
        p("Geen artikelen gevonden.")
      } else {
        shinyplus_env$new_items <- new_items # save to pkg envir to be able to save with button later
        n_new <- NROW(new_items)
        output$product_search <- renderUI({
          req(NROW(new_items) > 0)
          tagList(
            p(paste0("Deze ", n_new, " artikelen zijn gevonden die nieuw toegevoegd kunnen worden aan de artikelenlijst en vanaf dan beschikbaar zijn in deze app:")),
            actionButton("new_products_import", "Artikelen importeren en opslaan", icon = icon("list-check"), class = "btn-success", width = "100%"),
            br(),
            br(),
            div(style = "overflow-y: auto;",
                div(class = "row",
                    lapply(seq_len(nrow(new_items)), function(i) {
                      item <- new_items[i, ]
                      div(class = "col-md-4 mb-3",
                          div(class = "card h-100 shadow-sm",
                              img(src = item$img, class = "card-img-top", style = "max-height: 150px; object-fit: contain;"),
                              div(class = "card-body",
                                  h6(class = "card-title", item$name),
                                  p(class = "card-text", item$unit),
                                  a(href = plus_url(item$url), target = "_blank", class = "btn btn-sm btn-primary",
                                    HTML('<i class="fas fa-right-from-bracket" role="presentation" aria-label="magnifying-glass icon"></i> Bekijken op PLUS.nl'))
                              )
                          )
                      )
                    })
                )
            ),
          )
        })
      }
    }

    observeEvent(input$new_products_import, {
      backup_product_list()
      shinyplus_env$product_list <- shinyplus_env$product_list |>
        bind_rows(shinyplus_env$new_items) |>
        arrange(name)
      # update RDS, input fields
      product_list_last_updated(Sys.time())
      updateTextInput(session, inputId = "product_search_txt", value = "")
      updateTextAreaInput(session, inputId = "product_import_html", value = "")
      output$product_search <- renderUI({
        p("Gereed. Druk op de zoek- of importeerknop om opnieuw te beginnen.")
      })
    })

    observeEvent(input$open_searchpage, {
      runjs(sprintf("window.open('%s', '_blank')", plus_url("producten")))
    })

  }

  shinyApp(ui, server)
}

sort_dish_df <- function(dishes, method) {
  sort_field <- switch(method,
                       "Naam" = "name",
                       "Bereidingstijd" = "preptime",
                       "Hoeveelheid groenten" = "vegetables",
                       "Type vlees/vis/vega" = "meat",
                       "preptime")

  if (sort_field == "name") {
    arrange(dishes, name)
  } else if (sort_field == "preptime") {
    arrange(dishes, preptime, desc(vegetables))
  } else if (sort_field == "vegetables") {
    arrange(dishes, desc(vegetables), preptime)
  } else if (sort_field == "meat") {
    arrange(dishes, desc(meat), desc(vegetables), preptime)
  } else {
    dishes
  }
}

preptime_icon <- function(x) {
  vapply(FUN.VALUE = character(1),
         x,
         function(xx)
           switch(as.character(xx),
                  " " = "\U2753",
                  `NA` = "\U2753",
                  "20" = "0-20 min",
                  "40" = "20-40 min",
                  "60" = "40-60 min",
                  "120" = "60+ min",
                  paste0(xx, "+")),
         USE.NAMES = FALSE)
}

meat_icon <- function(type) {
  vapply(FUN.VALUE = character(1),
         type,
         function(tt)
           switch(tolower(as.character(tt)),
                  " " = "\U2753",
                  `NA` = "\U2753",
                  "vegetarisch" = "\U1F331",
                  "kip" = "\U1F413",
                  "rund" = "\U1F404",
                  "varken" = "\U1F416",
                  "vis" = "\U1F41F",
                  "gecombineerd" = "Combi",
                  as.character(tt)),
         USE.NAMES = FALSE)
}

vegetables_icon <- function(type) {
  vapply(FUN.VALUE = character(1),
         type,
         function(tt)
           switch(as.character(tt),
                  " " = "\U2753",
                  `NA` = "\U2753",
                  "0" = "\U2796",
                  "1" = "\U1F966",
                  "2" = "\U1F966\U1F966",
                  "3" = "\U1F966\U1F966\U1F966",
                  as.character(tt)),
         USE.NAMES = FALSE)
}

#' @importFrom shiny icon
plus_cart_text <- function(include_span = TRUE) {
  if (include_span == TRUE) {
    paste0("<span class='text-success'>", icon("cart-shopping"), " PLUS Winkelwagen</span>")
  } else {
    paste0(icon("cart-shopping"), " PLUS Winkelwagen")
  }
}
